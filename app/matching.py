"""Transparent role matching and relevance scoring."""
import re
from datetime import datetime, timezone

DEFAULT_ROLES = ["Cybersecurity", "Information Security", "Security Analyst", "Security Engineer", "SOC Analyst", "Cyber Defense", "Application Security", "Product Security", "Vulnerability Assessment", "Penetration Testing", "Cloud Security", "Infrastructure Security", "Network Security", "DevSecOps", "AI Security", "LLM Security"]
def words(s): return set(re.findall(r"[a-z0-9+#.]{2,}", (s or "").lower()))

def score_job(job: dict, profile: dict) -> dict:
    title, body = job.get("title", ""), (job.get("description", "") or "")
    title_terms = [t for t in profile.get("preferred_titles", DEFAULT_ROLES) if t.strip()]
    skills = [x for x in profile.get("skills", []) if x.strip()]
    keywords = [x for x in profile.get("optional_keywords", []) if x.strip()]
    required = [x for x in profile.get("required_keywords", []) if x.strip()]
    title_hit = [x for x in title_terms if words(x) & words(title)]
    skill_hit = [x for x in skills if words(x) and words(x) <= words(title + " " + body)]
    keyword_hit = [x for x in keywords if words(x) and words(x) <= words(title + " " + body)]
    required_hit = [x for x in required if words(x) and words(x) <= words(title + " " + body)]
    points = (35 * bool(title_hit) + 20 * (len(skill_hit) / max(1, len(skills))) + 15 * (len(keyword_hit) / max(1, len(keywords))) + 15 * (len(required_hit) / max(1, len(required))))
    exp, _ = __import__("app.experience", fromlist=["classify_experience"]).classify_experience(body, int(profile.get("max_experience", 3)))
    points += 10 if exp == "confirmed" else 4 if exp == "needs_review" else 0
    locs = [x.lower() for x in profile.get("target_locations", [])]
    loc = (job.get("location") or "").lower()
    points += 5 if job.get("remote") and profile.get("remote_preference", True) else 5 if any(x in loc for x in locs) else 0
    published = job.get("published_at")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(published.replace("Z", "+00:00"))).days
        points += max(0, 5 * (1 - age / 30))
    except Exception: pass
    return {"score": round(min(100, points)), "matching_skills": skill_hit, "uncertain_skills": [x for x in skills if x not in skill_hit], "match_explanation": ("Title match: " + ", ".join(title_hit) + ". " if title_hit else "No direct title match. ") + ("Matching skills: " + ", ".join(skill_hit) + "." if skill_hit else "No configured skills found in the posting.")}
