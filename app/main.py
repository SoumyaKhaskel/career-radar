import asyncio, csv, io, json, logging, os, re
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from app import db
from app.collectors import DOCS, collect, parse_ats_url
from app.experience import classify_experience
from app.matching import score_job

ROOT=Path(__file__).resolve().parent.parent
load_dotenv(ROOT/".env")
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s")
log=logging.getLogger("career_radar")
app=FastAPI(title="Career Radar",docs_url=None,redoc_url=None)
app.mount("/static",StaticFiles(directory=str(ROOT/"app"/"static")),name="static")
templates=Jinja2Templates(directory=str(ROOT/"app"/"templates"))
db.init()
scan_lock=asyncio.Lock()

@app.get("/",response_class=HTMLResponse)
def dashboard(request: Request, q="", category="", country="", workplace="", employment="", source="", sort="relevance", saved=False, review=True, minimum=0):
    profile=json.loads(db.setting("profile","{}")); clauses=["dismissed=0", "experience_class!='excluded'"]; args=[]
    if not country:
        country="India"
    if q: clauses.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)"); args += [f"%{q}%"]*3
    if category: clauses.append("title LIKE ?"); args.append(f"%{category}%")
    if country.lower()=="india":
        targets=list(dict.fromkeys(profile.get("target_locations",[])+["India","Kolkata","Hyderabad","Bengaluru","Bangalore"]))
        clauses.append("("+" OR ".join(["country LIKE ?"]+["location LIKE ?"]*len(targets))+")")
        args += ["%India%"]+[f"%{value}%" for value in targets]
    elif country: clauses.append("(country LIKE ? OR location LIKE ?)"); args += [f"%{country}%"]*2
    if workplace=="Remote": clauses.append("remote=1")
    elif workplace in ("Hybrid","On-site"): clauses.append("workplace LIKE ?"); args.append(f"%{workplace}%")
    if employment: clauses.append("employment_type LIKE ?"); args.append(f"%{employment}%")
    if source: clauses.append("sources LIKE ?"); args.append(f"%{source}%")
    if saved: clauses.append("saved=1")
    if not review: clauses.append("experience_class='confirmed'")
    clauses.append("score>=?"); args.append(int(minimum))
    order={"relevance":"score DESC, published_at DESC","date":"published_at DESC","company":"company COLLATE NOCASE","location":"location COLLATE NOCASE"}.get(sort,"score DESC")
    with db.connect() as c:
        jobs=[dict(r) for r in c.execute(f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT 300",args)]
        total=c.execute(f"SELECT COUNT(*) FROM jobs WHERE {' AND '.join(clauses)}",args).fetchone()[0]
        counts={r["experience_class"]:r["n"] for r in c.execute("SELECT experience_class,COUNT(*) n FROM jobs WHERE dismissed=0 GROUP BY experience_class")}
        sources=[dict(r) for r in c.execute("SELECT * FROM sources ORDER BY provider,company")]
        last_scan=dict(c.execute("SELECT * FROM scans WHERE status='complete' ORDER BY id DESC LIMIT 1").fetchone() or {})
    for j in jobs:
        for k in ("matching_skills","uncertain_skills","sources"):
            try:j[k]=json.loads(j[k] or "[]")
            except Exception:j[k]=[]
    return templates.TemplateResponse(request=request,name="dashboard.html",context={"jobs":jobs,"total":total,"counts":counts,"sources":sources,"last_scan":last_scan,"q":q,"category":category,"country":country,"workplace":workplace,"employment":employment,"source":source,"sort":sort,"saved":saved,"review":review,"minimum":minimum,"profile":profile,"adzuna_ready":bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY"))})

@app.post("/scan")
async def run_scan():
    if scan_lock.locked(): return PlainTextResponse("A scan is already running.",status_code=409)
    async with scan_lock:
        started=datetime.now(timezone.utc).isoformat(); inserted=updated=retrieved=0; status="failed"; source_results={}
        with db.connect() as c:
            cur=c.execute("INSERT INTO scans(started_at,status) VALUES(?, 'running')",(started,)); scan_id=cur.lastrowid
            configs=[dict(provider=r["provider"],board_token=r["board_token"],company=r["company"],region=r["region"]) for r in c.execute("SELECT * FROM sources WHERE enabled=1")]
        profile=json.loads(db.setting("profile","{}"))
        terms=profile.get("preferred_titles",[])+profile.get("required_keywords",[])+profile.get("optional_keywords",[])
        for cfg in configs:
            if cfg["provider"]=="Adzuna": cfg["query_terms"]=terms
        results=await collect(configs)
        for cfg,jobs,error in results:
            name=f"{cfg['provider']} — {cfg['company'] or cfg['board_token']}"; source_results[name]={"retrieved":len(jobs),"error":error}
            with db.connect() as c:
                c.execute("UPDATE sources SET last_success=?,last_error=? WHERE provider=? AND board_token=?",(datetime.now(timezone.utc).isoformat() if (jobs or not error) else None,error,cfg["provider"],cfg["board_token"]))
            if error: log.warning("Source returned warnings/errors: %s (%s)",name,error)
            if error and not jobs: continue
            retrieved+=len(jobs)
            for job in jobs:
                exp,reason=classify_experience(job.get("description"),int(profile.get("max_experience",3)))
                job.update(experience_text="",experience_class=exp,experience_reason=reason,**score_job(job,profile))
                if db.upsert_job(job): inserted+=1
                else: updated+=1
        status="complete" if any(jobs or not error for _,jobs,error in results) else "failed"
        with db.connect() as c: c.execute("UPDATE scans SET finished_at=?,status=?,retrieved=?,inserted=?,updated=?,source_results=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),status,retrieved,inserted,updated,json.dumps(source_results),scan_id))
    return RedirectResponse("/?scan=complete",status_code=303)

@app.post("/sources/add")
def add_source(url: str=Form(...), company: str=Form("")):
    try: provider,token,region=parse_ats_url(url)
    except ValueError as e: return PlainTextResponse(str(e),status_code=400)
    with db.connect() as c: c.execute("INSERT OR IGNORE INTO sources(provider,board_token,company,region) VALUES(?,?,?,?)",(provider,token,company.strip() or token,region))
    return RedirectResponse("/",status_code=303)

@app.post("/sources/{source_id}/toggle")
def toggle_source(source_id:int):
    with db.connect() as c:c.execute("UPDATE sources SET enabled=1-enabled WHERE id=?",(source_id,))
    return RedirectResponse("/",status_code=303)

@app.post("/jobs/{job_id}/update")
def update_job(job_id:int,saved:bool=Form(False),application_status:str=Form("none"),applied_date:str=Form(""),note:str=Form(""),dismissed:bool=Form(False)):
    with db.connect() as c:c.execute("UPDATE jobs SET saved=?,application_status=?,applied_date=?,note=?,dismissed=? WHERE id=?",(int(saved),application_status,applied_date or None,note,int(dismissed),job_id))
    return RedirectResponse("/",status_code=303)

@app.get("/settings",response_class=HTMLResponse)
def settings_page(request:Request):
    profile=json.loads(db.setting("profile","{}"))
    return templates.TemplateResponse(request=request,name="settings.html",context={"profile":profile,"schedule_time":db.setting("schedule_time","09:00"),"schedule_days":db.setting("schedule_days","Monday,Wednesday,Friday")})

@app.post("/settings")
def save_settings(preferred_titles:str=Form(""),required_keywords:str=Form(""),optional_keywords:str=Form(""),target_locations:str=Form(""),remote_preference:bool=Form(False),max_experience:int=Form(3),skills:str=Form(""),education:str=Form(""),certifications:str=Form(""),summary:str=Form(""),resume_text:str=Form(""),schedule_time:str=Form("09:00"),show_review:bool=Form(True)):
    lines=lambda x:[v.strip() for v in re.split(r"[,\n]",x) if v.strip()]
    profile={"preferred_titles":lines(preferred_titles),"required_keywords":lines(required_keywords),"optional_keywords":lines(optional_keywords),"target_locations":lines(target_locations),"remote_preference":remote_preference,"max_experience":min(3,max(0,max_experience)),"skills":lines(skills),"education":lines(education),"certifications":lines(certifications),"summary":summary,"resume_text":resume_text}
    db.set_setting("profile",json.dumps(profile));db.set_setting("schedule_time",schedule_time);db.set_setting("show_review",str(show_review).lower())
    return RedirectResponse("/settings?saved=1",status_code=303)

@app.get("/export.csv")
def export_csv():
    output=io.StringIO(); fields=["title","company","location","country","workplace","employment_type","experience_text","experience_class","score","matching_skills","source","url","published_at","first_detected","application_status","applied_date","note"]
    w=csv.DictWriter(output,fieldnames=fields);w.writeheader()
    with db.connect() as c:
        for r in c.execute("SELECT * FROM jobs WHERE dismissed=0 ORDER BY score DESC"):
            d=dict(r);d["matching_skills"]=", ".join(json.loads(d["matching_skills"] or "[]"));w.writerow({k:d.get(k) for k in fields})
    return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=career-radar.csv"})

@app.post("/data/delete")
def delete_data():
    with db.connect() as c:c.execute("DELETE FROM jobs");c.execute("DELETE FROM scans");c.execute("DELETE FROM settings WHERE key='profile'")
    db.init()
    return RedirectResponse("/",status_code=303)
