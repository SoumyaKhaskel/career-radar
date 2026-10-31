# Career Radar

Local-first job discovery and application tracking for public company ATS boards. The dashboard now defaults to India and prioritises Kolkata, Hyderabad, and Bengaluru/Bangalore. Coverage is limited to configured boards and is never represented as worldwide or exhaustive.

## Requirements and start (Windows PowerShell)

Use Python 3.10 or newer. From this project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The app binds to localhost. The dashboard profile, job history, notes, and settings are stored in `data/career_radar.sqlite3`.

## Sources

Add an official ATS board URL in the dashboard, such as `https://boards.greenhouse.io/acme`, `https://jobs.lever.co/acme`, `https://jobs.eu.lever.co/acme`, or `https://jobs.ashbyhq.com/acme`. The app parses only these supported URLs and calls public documented postings endpoints. Each query uses bounded retry, a 20-second timeout, a concurrency cap, and no arbitrary-domain crawler. Source errors are retained in the dashboard and do not close existing jobs.

| Provider | Access | Official docs / terms | Configuration |
|---|---|---|---|
| Greenhouse | Public Job Board API GET; no auth | [Job Board API](https://docs.greenhouse.io/job-board) | Board token from public board URL |
| Lever | Public published Postings API | [Postings API](https://github.com/lever/postings-api) | Site name from public board URL; global or EU |
| Ashby | Public Job Posting API for published postings | [Public API](https://developers.ashbyhq.com/docs/public-job-posting-api) | Board name from public board URL |
| Adzuna | India job search API; personal job search is permitted, credentials and attribution required | [Search API](https://developer.adzuna.com/docs/search) · [Terms](https://developer.adzuna.com/docs/terms_of_service) | `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env` |

The Adzuna India source is enabled by default; add its credentials to `.env` to turn on automatic search for the saved role and keyword list. Each scan makes up to 20 role/keyword searches, one result page of 20 listings per query, with a per-source request rate cap. Adzuna responses may include only a description snippet. Built-in quick links open LinkedIn and Indeed searches for the three target cities, Naukri, and official HCLTech and IBM careers pages. Those portals are manual links only: the app does not import, crawl, or scrape their listings. Restricted portals (including LinkedIn, Indeed, and Naukri) are not crawled.

### Enable Adzuna India searches

1. Register for an API ID and key at [developer.adzuna.com](https://developer.adzuna.com/).
2. Copy `.env.example` to `.env` if you have not already done so.
3. Open `.env` in a local text editor and fill in `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`. Do not send these credentials in chat or add them to source code.
4. Restart Uvicorn. The dashboard should show Adzuna credentials as configured.
5. Set your roles and locations in **Profile & Settings**, then click **Run Scan Now**. The first scan requests up to 20 India role searches, with bounded retries. A live scan requires valid credentials and is not verified by the mocked tests.

## Use

- Run a scan from **Run Scan Now**, or from PowerShell: `python -m app.scan_cli`.
- Update roles, keywords, skills, locations, profile, and resume text at **Profile & Settings**. Resume text remains local and is never sent to an AI service.
- Filter, sort, save, track interest/application/date/private note, dismiss, and export from the dashboard.
- Experience is classified against the profile maximum (capped at 3 in this version). Unclear or absent requirements go to **needs review**. The score is a deterministic estimate, not a hiring probability; see below.
- Add more ATS boards over time. Duplicate URLs collapse into one row with source references.

### Score model

The score adds up to 100 points: title overlap 35; configured skill overlap 20; optional keyword overlap 15; required keyword overlap 15; experience compatibility 10 (confirmed 10, needs review 4, excluded 0); location or remote preference 5; and recency up to 5. Each category is capped by its weight. The overlapping base weights total 105, then the result is capped at 100. Matching skills are literal token overlaps and do not claim that the user's profile contains skills from the job description.

## Automatic schedule

The default configuration is Monday, Wednesday, Friday at 09:00 Asia/Kolkata, but it is not enabled automatically. Configure the time in settings, then run an elevated PowerShell only if your machine policy requires it:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-schedule.ps1 -Time "09:00"
```

The task runs `python -m app.scan_cli` without the dashboard. To disable it: `.scriptsemove-schedule.ps1`. To test immediately: `Start-ScheduledTask -TaskName 'Career Radar Scan'` or run `python -m app.scan_cli` directly. Check Task Scheduler history and `data/career_radar.sqlite3` scan history through the app. The PC must be on at schedule time; Windows **Start the task as soon as possible after a scheduled start is missed** is enabled by `-StartWhenAvailable`. Set the Windows system time zone to Asia/Kolkata for the entered time to match the configured time; Windows Task Scheduler interprets the time using the machine's local zone.

The scheduler script uses Monday/Wednesday/Friday as fixed default days; the web UI exposes the configured time but does not yet support changing weekdays or showing stored schedule configuration dynamically. It deliberately does not install itself automatically.

## Tests and limitations

Run `pytest`. Tests are local and deterministic; Adzuna requests are mocked and do not call live APIs. The public endpoint behavior was checked against official documentation, but a live Adzuna scan remains unverified until you add your credentials. The current build does not provide job-detail modal, real scan progress/cancellation, pagination beyond the first 300 dashboard rows, or closure inference from provider disappearance. A successful-source scan refreshes detected jobs; a failed scan leaves old records active. Source and scan status is recorded locally.

## Data and privacy

API keys belong in `.env`; `.env`, database files, and logs are git-ignored. This app currently binds to `127.0.0.1`. Use the settings page's delete control to remove job history and profile; configured source boards remain. No application submission or recruiter contact is performed.
