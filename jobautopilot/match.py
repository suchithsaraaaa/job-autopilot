"""Decide whether a posting fits the profile, and how well (0-100)."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .classify import classify_job
from .models import Job

_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?(?:years?|yrs?)[^.\n]{0,50}?(?:experience|exp\b)"
    r"|experience[^.\n]{0,30}?(\d{1,2})\s*\+?\s*(?:years?|yrs?)"
    r"|(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+of\s+(?:software|backend|python|web|development|engineering|professional|industry|hands-on|work)"
    r"|(?:minimum|at least)\s+(\d{1,2})\s*\+?\s*(?:years?|yrs?)",
    re.I
)
_NON_INDIA_REMOTE = re.compile(
    r"\b(us|usa|u\.s\.|united states|canada|uk|united kingdom|europe|emea|eu|latam|"
    r"brazil|mexico|australia)\b", re.I)


@dataclass
class Match:
    ok: bool
    score: int = 0
    reasons: list[str] = field(default_factory=list)   # why it was rejected
    hits: list[str] = field(default_factory=list)       # profile skills found in the JD
    categories: list[str] = field(default_factory=list)
    eligibility: str = "unknown"



def _has(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def required_years(text: str) -> int | None:
    found = []
    for m in _YEARS.finditer(text):
        for g in m.groups():
            if g:
                found.append(int(g))
    return min(found) if found else None


def location_ok(job: Job, prof: dict) -> bool:
    loc = job.location.lower()
    if any(x.lower() in loc for x in prof["locations"]["include"]):
        return True
    if prof["locations"].get("remote_ok") and (job.remote or "remote" in loc):
        # Remote is fine unless it is restricted to another region.
        return not _NON_INDIA_REMOTE.search(job.location) or "india" in loc
    return False


def evaluate(job: Job, prof: dict, now: datetime | None = None) -> Match:
    classify_job(job)
    cats = job.categories
    elig = job.eligibility

    title = job.title
    t = prof["titles"]
    if not _has(t["include"], title):
        return Match(False, reasons=["title not in target roles"], categories=cats, eligibility=elig)
    if _has(t["exclude"], title):
        return Match(False, reasons=["title excluded (seniority/other field)"], categories=cats, eligibility=elig)
    if not location_ok(job, prof):
        return Match(False, reasons=[f"location: {job.location or 'unspecified'}"], categories=cats, eligibility=elig)

    text = f"{job.title}\n{job.description}"

    # If title is full-stack, enforce Python, Django, or Flask technical requirement
    if re.search(r"\bfull[- ]?stack\b", title, re.I):
        if not re.search(r"\b(python|django|flask)\b", text, re.I):
            return Match(False, reasons=["full-stack role does not require Python/Django/Flask"], categories=cats, eligibility=elig)

    if job.posted_at and prof.get("max_age_days"):
        try:
            posted = datetime.fromisoformat(job.posted_at.replace("Z", "+00:00"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            if (now or datetime.now(timezone.utc)) - posted > timedelta(days=prof["max_age_days"]):
                return Match(False, reasons=["posting too old"], categories=cats, eligibility=elig)
        except ValueError:
            pass

    yrs = required_years(text)
    if yrs is not None and yrs > prof.get("max_years_required", 1):
        return Match(False, reasons=[f"asks for {yrs}+ years"], categories=cats, eligibility=elig)

    hits = [s for s in prof["skills"] if re.search(rf"(?<![\w+#]){re.escape(s)}(?![\w+#])", text, re.I)]
    skill_part = 60 * min(1.0, len(hits) / max(1, prof.get("skills_for_full_score", 5)))
    entry_part = 25 if (_has(prof.get("entry_level_words", []), text) or "internship" in cats or elig == "2027 students eligible") else 0
    title_part = 15 if _has(prof.get("preferred_title_words", []), title) else 0
    score = round(skill_part + entry_part + title_part)
    if score < prof.get("min_score", 40):
        return Match(False, score, [f"score {score} below minimum"], hits, cats, elig)
    return Match(True, score, [], hits, cats, elig)

