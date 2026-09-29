"""Legitimacy gate. A posting must pass every check to be shown to you.

1. It comes from a company in config/companies.yaml (a hand-verified allowlist),
   fetched from that company's own ATS board, never from a job aggregator.
2. Its link is https and on a known ATS host or the company's own domain.
3. Its text has none of the classic job-scam tells (fees, WhatsApp/Telegram
   contact, cheque/wire tasks, "earn $X a day").
"""
import re
from urllib.parse import urlparse

ATS_HOSTS = (
    "boards.greenhouse.io", "job-boards.greenhouse.io", "greenhouse.io",
    "jobs.lever.co", "lever.co", "jobs.ashbyhq.com", "ashbyhq.com",
)

SCAM_PATTERNS = [
    r"registration fee", r"processing fee", r"training fee", r"security deposit",
    r"pay (?:a |the )?(?:small )?fee", r"refundable deposit",
    r"whatsapp", r"telegram (?:me|id|channel|group)", r"contact (?:us )?on signal",
    r"wire transfer", r"western union", r"gift cards?", r"cheque|check deposit",
    r"earn \$?\d[\d,]*\s*(?:per|a|/)\s*(?:day|hour|week)",
    r"no (?:interview|experience) (?:needed|required).{0,40}(?:earn|salary)",
    r"guaranteed (?:income|job|placement)",
]
_SCAM = re.compile("|".join(SCAM_PATTERNS), re.I)
_PERSONAL_MAIL = re.compile(r"[\w.+-]+@(?:gmail|yahoo|outlook|hotmail|proton)\.\w+", re.I)


def host_ok(url: str, extra_domains: list[str] | None = None) -> bool:
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        return False
    host = p.hostname.lower()
    allowed = list(ATS_HOSTS) + [d.lower() for d in (extra_domains or [])]
    return any(host == d or host.endswith("." + d) for d in allowed)


def check(job, company: dict) -> tuple[bool, list[str]]:
    reasons = []
    if not host_ok(job.url, company.get("domains")):
        reasons.append(f"link not on a known ATS or company domain: {job.url[:80]}")
    if job.apply_url and not host_ok(job.apply_url, company.get("domains")):
        reasons.append("apply link not on a known ATS or company domain")
    text = f"{job.title}\n{job.description}"
    m = _SCAM.search(text)
    if m:
        reasons.append(f"scam-style wording: '{m.group(0)}'")
    if _PERSONAL_MAIL.search(text):
        reasons.append("recruiter uses a personal email address")
    return (not reasons), reasons
