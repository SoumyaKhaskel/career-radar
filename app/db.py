import json, sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent.parent
DB_PATH=ROOT/"data"/"career_radar.sqlite3"
class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()
def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=15,factory=_Connection); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA foreign_keys=ON"); return c
def init(path=DB_PATH):
    with connect(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, dedupe_key TEXT UNIQUE, source TEXT, source_id TEXT, title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, country TEXT, url TEXT NOT NULL, description TEXT, published_at TEXT, workplace TEXT, remote INTEGER DEFAULT 0, employment_type TEXT, experience_text TEXT, experience_class TEXT, experience_reason TEXT, score INTEGER DEFAULT 0, matching_skills TEXT DEFAULT '[]', uncertain_skills TEXT DEFAULT '[]', match_explanation TEXT, first_detected TEXT, last_detected TEXT, last_verified TEXT, status TEXT DEFAULT 'active', saved INTEGER DEFAULT 0, application_status TEXT DEFAULT 'none', applied_date TEXT, note TEXT DEFAULT '', dismissed INTEGER DEFAULT 0, sources TEXT DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, provider TEXT, board_token TEXT, company TEXT, region TEXT DEFAULT 'global', enabled INTEGER DEFAULT 1, last_success TEXT, last_error TEXT, UNIQUE(provider,board_token));
        CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, retrieved INTEGER DEFAULT 0, inserted INTEGER DEFAULT 0, updated INTEGER DEFAULT 0, source_results TEXT DEFAULT '{}', error TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        """)
        defaults={"profile":json.dumps({"preferred_titles": ["Cybersecurity","Information Security","Security Analyst","Security Engineer","SOC Analyst","Cyber Defense","Application Security","Product Security","Vulnerability Assessment","Penetration Testing","Cloud Security","Infrastructure Security","Network Security","DevSecOps","AI Security","LLM Security"],"required_keywords":[],"optional_keywords":[],"target_locations":["India","Kolkata","Hyderabad","Bengaluru","Bangalore"],"remote_preference":True,"max_experience":3,"skills":[],"education":[],"certifications":[],"summary":"","resume_text":""}),"show_review":"true","schedule_days":"Monday,Wednesday,Friday","schedule_time":"09:00","schedule_timezone":"Asia/Kolkata"}
        for k,v in defaults.items(): c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)",(k,v))
        c.execute("INSERT OR IGNORE INTO sources(provider,board_token,company,region,enabled) VALUES('Adzuna','in','Adzuna India','India',1)")
        # Migrate the original untouched default; preserve any locations the user already edited.
        row=c.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
        if row:
            profile=json.loads(row[0])
            if profile.get("target_locations")==["India"]:
                profile["target_locations"]=["India","Kolkata","Hyderabad","Bengaluru","Bangalore"]
            original_titles=["Cybersecurity","Security Analyst","Security Engineer","SOC Analyst","Application Security","Cloud Security","DevSecOps","AI Security"]
            if profile.get("preferred_titles")==original_titles:
                profile["preferred_titles"]=json.loads(defaults["profile"])["preferred_titles"]
            c.execute("UPDATE settings SET value=? WHERE key='profile'",(json.dumps(profile),))
def setting(key, default=None, path=DB_PATH):
    with connect(path) as c: r=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone(); return r[0] if r else default
def set_setting(key,value,path=DB_PATH):
    with connect(path) as c: c.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))
def key_for(j):
    import re
    url=(j.get("url") or "").split("?")[0].rstrip("/").lower()
    if url: return "url:"+url
    norm=lambda s: re.sub(r"[^a-z0-9]","",(s or "").lower())
    return "title:"+"|".join((norm(j.get("company")),norm(j.get("title")),norm(j.get("location"))))
def upsert_job(j,path=DB_PATH):
    now=datetime.now(timezone.utc).isoformat(); dk=key_for(j)
    with connect(path) as c:
        old=c.execute("SELECT id,sources,first_detected,saved,application_status,applied_date,note,dismissed FROM jobs WHERE dedupe_key=?",(dk,)).fetchone()
        if old is None:
            # Cross-provider fallback for canonical URLs that differ for the same vacancy.
            candidates=c.execute("SELECT id,sources,first_detected,saved,application_status,applied_date,note,dismissed,company,title,location FROM jobs WHERE lower(company)=lower(?) AND lower(title)=lower(?) AND lower(coalesce(location,''))=lower(?)",(j.get("company") or "Unknown company",j.get("title") or "Unknown title",j.get("location") or "")).fetchall()
            norm=lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum())
            old=next((r for r in candidates if norm(r["company"])==norm(j.get("company")) and norm(r["title"])==norm(j.get("title")) and norm(r["location"])==norm(j.get("location"))),None)
        sources=set(json.loads(old["sources"])) if old else set(); sources.add(j["source"])
        vals=(dk,j.get("source"),j.get("source_id"),j.get("title") or "Unknown title",j.get("company") or "Unknown company",j.get("location"),j.get("country"),j.get("url") or "",j.get("description"),j.get("published_at"),j.get("workplace"),int(bool(j.get("remote"))),j.get("employment_type"),j.get("experience_text"),j.get("experience_class","needs_review"),j.get("experience_reason"),j.get("score",0),json.dumps(j.get("matching_skills",[])),json.dumps(j.get("uncertain_skills",[])),j.get("match_explanation"),now,now,now,"active",json.dumps(sorted(sources)))
        if old:
            c.execute("""UPDATE jobs SET source=?,source_id=?,title=?,company=?,location=?,country=?,url=?,description=?,published_at=?,workplace=?,remote=?,employment_type=?,experience_text=?,experience_class=?,experience_reason=?,score=?,matching_skills=?,uncertain_skills=?,match_explanation=?,last_detected=?,last_verified=?,status='active',sources=? WHERE id=?""",vals[1:20]+(now,now, json.dumps(sorted(sources)),old["id"]))
            return False
        sql = "INSERT INTO jobs(dedupe_key,source,source_id,title,company,location,country,url,description,published_at,workplace,remote,employment_type,experience_text,experience_class,experience_reason,score,matching_skills,uncertain_skills,match_explanation,first_detected,last_detected,last_verified,status,sources) VALUES(" + ",".join("?" for _ in range(25)) + ")"
        c.execute(sql,vals)
        return True
