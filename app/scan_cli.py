"""Run a scan without starting the web dashboard (for Task Scheduler)."""
import asyncio, json, logging
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from app import db
from app.collectors import collect
from app.experience import classify_experience
from app.matching import score_job

load_dotenv(Path(__file__).resolve().parent.parent/".env")

async def main():
    db.init(); started=datetime.now(timezone.utc).isoformat()
    with db.connect() as c:
        sid=c.execute("INSERT INTO scans(started_at,status) VALUES(?, 'running')",(started,)).lastrowid
        cfg=[dict(provider=r["provider"],board_token=r["board_token"],company=r["company"],region=r["region"]) for r in c.execute("SELECT * FROM sources WHERE enabled=1")]
    profile=json.loads(db.setting("profile","{}")); terms=profile.get("preferred_titles",[])+profile.get("required_keywords",[])+profile.get("optional_keywords",[])
    for source in cfg:
        if source["provider"]=="Adzuna": source["query_terms"]=terms
    results=await collect(cfg); retrieved=inserted=updated=0; report={}
    for source,jobs,error in results:
        name=f"{source['provider']} — {source['company']}"; report[name]={"retrieved":len(jobs),"error":error}
        with db.connect() as c:c.execute("UPDATE sources SET last_success=?,last_error=? WHERE provider=? AND board_token=?",(datetime.now(timezone.utc).isoformat() if (jobs or not error) else None,error,source["provider"],source["board_token"]))
        if error: logging.error("%s: %s",name,error)
        if error and not jobs: continue
        retrieved+=len(jobs)
        for job in jobs:
            cl,why=classify_experience(job.get("description"),int(profile.get("max_experience",3)));job.update(experience_class=cl,experience_reason=why,**score_job(job,profile))
            if db.upsert_job(job):inserted+=1
            else:updated+=1
    status="complete" if any(jobs or not error for _,jobs,error in results) else "failed"
    with db.connect() as c:c.execute("UPDATE scans SET finished_at=?,status=?,retrieved=?,inserted=?,updated=?,source_results=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),status,retrieved,inserted,updated,json.dumps(report),sid))
    print(json.dumps({"status":status,"retrieved":retrieved,"inserted":inserted,"updated":updated,"sources":report},indent=2))
    return 0 if status=="complete" else 1
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
