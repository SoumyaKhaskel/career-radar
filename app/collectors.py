"""Public, documented job board adapters. No arbitrary-domain crawling."""
import asyncio, html, os, re
from urllib.parse import urlparse
import httpx

DOCS = {
 "Greenhouse": ("Greenhouse Job Board API", "https://docs.greenhouse.io/job-board", "Public JSON GET; board token required", "Public board token"),
 "Lever": ("Lever Postings API", "https://github.com/lever/postings-api", "Published postings JSON; site name required", "Site name; optional EU region"),
 "Ashby": ("Ashby Public Job Posting API", "https://developers.ashbyhq.com/docs/public-job-posting-api", "Public job board JSON; board name required", "Job board name"),
 "Adzuna": ("Adzuna API", "https://developer.adzuna.com/docs/search", "Personal job search permitted; display attribution required", "ADZUNA_APP_ID and ADZUNA_APP_KEY in .env"),
}

def parse_ats_url(value: str):
    """Accept only known official ATS board URLs, returning (provider, token, region)."""
    p = urlparse(value)
    host = (p.hostname or "").lower()
    parts = [x for x in p.path.split("/") if x]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and parts:
        return "Greenhouse", parts[0], "global"
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and parts:
        return "Lever", parts[0], "eu" if host == "jobs.eu.lever.co" else "global"
    if host == "jobs.ashbyhq.com" and parts:
        return "Ashby", parts[0], "global"
    raise ValueError("URL is not a recognized public Greenhouse, Lever, or Ashby job board.")

def _job(source, ident, title, company, loc, url, desc="", published=None, workplace=None, emp=None):
    if not title or not url: return None
    return {"source":source,"source_id":str(ident or url),"title":html.unescape(str(title)).strip(),"company":str(company or "Unknown company").strip(),"location":str(loc or "Unspecified"),"country":"","url":url,"description":re.sub(r"<[^>]+>"," ",html.unescape(str(desc or ""))),"published_at":published,"workplace":workplace,"remote":str(workplace or "").lower() in {"remote","hybrid"},"employment_type":emp,"experience_text":""}

def adzuna_search_url(country="in",page=1):
    return f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

def adzuna_params(query,app_id,app_key):
    return {"app_id":app_id,"app_key":app_key,"results_per_page":20,"what":query,"content-type":"application/json"}

def adzuna_credentials(app_id,app_key):
    app_id=(app_id or "").strip();app_key=(app_key or "").strip()
    if not app_id or not app_key:
        raise RuntimeError("Add ADZUNA_APP_ID and ADZUNA_APP_KEY to the local .env file, then restart Career Radar.")
    return app_id,app_key

def parse_adzuna_payload(payload):
    jobs=[]
    for item in payload.get("results",[]):
        location=(item.get("location") or {}).get("display_name") or "Unspecified"
        company=(item.get("company") or {}).get("display_name") or "Unknown company"
        workplace="Remote" if re.search(r"\b(remote|work from home|work-from-home)\b",f"{location} {item.get('description','')}",re.I) else None
        job=_job("Adzuna",item.get("id"),item.get("title"),company,location,item.get("redirect_url"),item.get("description"),item.get("created"),workplace,item.get("contract_time") or item.get("contract_type"))
        if job:
            job["country"]="India"
            jobs.append(job)
    return jobs

async def fetch_source(client, config):
    provider, token, region = config["provider"], config["board_token"], config.get("region","global")
    if provider == "Greenhouse":
        r=await client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",params={"content":"true"}); r.raise_for_status(); data=r.json()
        jobs=[]
        for x in data.get("jobs",[]):
            offices=x.get("offices") or []; loc=", ".join(filter(None,[o.get("location") for o in offices])) or "Unspecified"
            # Greenhouse's updated_at is not a publication timestamp; keep published_at unknown.
            jobs.append(_job("Greenhouse",x.get("id"),x.get("title"),config.get("company") or token,loc,x.get("absolute_url"),x.get("content")))
        return [j for j in jobs if j]
    if provider == "Lever":
        host="api.eu.lever.co" if region=="eu" else "api.lever.co"
        r=await client.get(f"https://{host}/v0/postings/{token}",params={"mode":"json"}); r.raise_for_status(); data=r.json()
        jobs=[]
        for x in data if isinstance(data,list) else []:
            cats=x.get("categories") or {}
            jobs.append(_job("Lever",x.get("id"),x.get("text"),config.get("company") or token,cats.get("location"),x.get("hostedUrl"),x.get("descriptionPlain") or x.get("description"),x.get("createdAt") and __import__("datetime").datetime.fromtimestamp(x["createdAt"]/1000,__import__("datetime").timezone.utc).isoformat(),x.get("workplaceType"),cats.get("commitment")))
        return [j for j in jobs if j]
    if provider == "Ashby":
        r=await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}"); r.raise_for_status(); data=r.json()
        jobs=[]
        for x in data.get("jobs",[]):
            if x.get("isListed") is False: continue
            addr=(x.get("address") or {}).get("postalAddress") or {}
            jobs.append(_job("Ashby",x.get("jobUrl"),x.get("title"),config.get("company") or token,x.get("location"),x.get("jobUrl"),x.get("descriptionPlain"),x.get("publishedAt"),x.get("workplaceType"),x.get("employmentType")))
        return [j for j in jobs if j]
    if provider == "Adzuna":
        app_id,app_key=adzuna_credentials(os.getenv("ADZUNA_APP_ID"),os.getenv("ADZUNA_APP_KEY"))
        queries=list(dict.fromkeys(q.strip() for q in config.get("query_terms",[]) if q.strip()))[:20] or ["cybersecurity"]
        jobs=[]; errors=[]
        for index,query in enumerate(queries):
            if index: await asyncio.sleep(.5)  # Per-source cap: at most two search requests per second.
            payload=None
            for attempt in range(3):
                try:
                    r=await client.get(adzuna_search_url(),params=adzuna_params(query,app_id,app_key))
                    r.raise_for_status(); payload=r.json(); break
                except Exception as e:
                    if attempt==2:
                        status=f"HTTP {e.response.status_code}" if isinstance(e,httpx.HTTPStatusError) else type(e).__name__
                        errors.append(f"{query}: {status}")  # Never include request URLs or credential query params.
                    else:
                        await asyncio.sleep(.5*(2**attempt))
            if payload is not None: jobs.extend(parse_adzuna_payload(payload))
        if errors and not jobs: raise RuntimeError("Adzuna searches failed: " + "; ".join(errors))
        if errors: config["_partial_error"]="Some Adzuna searches failed: "+"; ".join(errors)
        return jobs
    raise ValueError(f"Unsupported provider: {provider}")

async def collect(configs):
    results=[]
    async with httpx.AsyncClient(timeout=httpx.Timeout(20),headers={"User-Agent":"CareerRadar/1.0 (local personal job search)"}) as client:
        sem=asyncio.Semaphore(2)
        async def one(c):
            async with sem:
                attempts=1 if c.get("provider")=="Adzuna" else 3
                for attempt in range(attempts):
                    try:
                        jobs=await fetch_source(client,c)
                        return c,jobs,c.get("_partial_error")
                    except Exception as e:
                        if attempt==attempts-1:
                            if c.get("provider")=="Adzuna":
                                status=f"HTTP {e.response.status_code}" if isinstance(e,httpx.HTTPStatusError) else type(e).__name__
                                return c,[],f"{status}: {e.args[0] if isinstance(e,RuntimeError) else 'Adzuna request failed'}"
                            return c,[],f"{type(e).__name__}: {e}"
                        await asyncio.sleep(.5*(2**attempt))
        results=await asyncio.gather(*(one(c) for c in configs))
    return results
