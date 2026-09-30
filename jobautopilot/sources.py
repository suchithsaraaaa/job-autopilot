"""Fetch jobs from the public job-board APIs of Greenhouse, Lever and Ashby.

Only companies listed in config/companies.yaml are ever queried, so every
posting comes straight from that company's own applicant-tracking system.
"""
import logging
from datetime import datetime, timezone

import requests

from .models import Job
from .textutil import html_to_text

log = logging.getLogger(__name__)
TIMEOUT = 25
HEADERS = {"User-Agent": "job-autopilot/1.0 (personal job search)"}


def _get(url: str):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_greenhouse(company: dict) -> list[Job]:
    slug = company["slug"]
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    jobs = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        jobs.append(Job(
            id=f"greenhouse:{slug}:{j['id']}", ats="greenhouse", company=company["name"],
            title=j.get("title", ""), location=loc, url=j.get("absolute_url", ""),
            apply_url=j.get("absolute_url", ""),
            description=html_to_text(j.get("content", "")),
            posted_at=j.get("updated_at"),
            department=", ".join(d.get("name", "") for d in j.get("departments", []) or []),
            remote="remote" in loc.lower(),
        ))
    return jobs


def fetch_lever(company: dict) -> list[Job]:
    slug = company["slug"]
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    jobs = []
    for j in data:
        cat = j.get("categories") or {}
        loc = cat.get("location") or ""
        desc = j.get("descriptionPlain", "")
        for lst in j.get("lists", []) or []:
            desc += "\n" + lst.get("text", "") + "\n" + html_to_text(lst.get("content", ""))
        desc += "\n" + j.get("additionalPlain", "")
        created = j.get("createdAt")
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
                  if created else None)
        jobs.append(Job(
            id=f"lever:{slug}:{j['id']}", ats="lever", company=company["name"],
            title=j.get("text", ""), location=loc, url=j.get("hostedUrl", ""),
            apply_url=j.get("applyUrl") or j.get("hostedUrl", ""),
            description=desc.strip(), posted_at=posted, department=cat.get("team") or "",
            remote=(j.get("workplaceType") == "remote") or "remote" in loc.lower(),
        ))
    return jobs


def fetch_ashby(company: dict) -> list[Job]:
    slug = company["slug"]
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        jobs.append(Job(
            id=f"ashby:{slug}:{j['id']}", ats="ashby", company=company["name"],
            title=j.get("title", ""), location=loc, url=j.get("jobUrl", ""),
            apply_url=j.get("applyUrl") or j.get("jobUrl", ""),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
            posted_at=j.get("publishedAt"), department=j.get("department") or "",
            remote=bool(j.get("isRemote")) or "remote" in loc.lower(),
        ))
    return jobs


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def fetch_all(companies: list[dict], source_type: str = "company") -> tuple[list[Job], list[str]]:
    """Returns (jobs, problems). One dead board never stops the run."""
    jobs, problems = [], []
    for c in companies:
        fetch = FETCHERS.get(c["ats"])
        if not fetch:
            problems.append(f"{c['name']}: unknown ats '{c['ats']}'")
            continue
        try:
            got = fetch(c)
            for j in got:
                if not j.source:
                    j.source = source_type
                if source_type == "startup" and "startup" not in j.categories:
                    j.categories.append("startup")
            log.info("%s (%s): %d postings", c["name"], c["ats"], len(got))
            jobs.extend(got)
        except Exception as e:  # network, 404 for a wrong slug, bad JSON
            problems.append(f"{c['name']} ({c['ats']}/{c['slug']}): {e}")
    return jobs, problems


def fetch_everything(companies: list[dict], startups: list[dict]) -> tuple[list[Job], list[str]]:
    """Fetch both verified enterprise companies and curated startups."""
    jobs, problems = fetch_all(companies, source_type="company")
    if startups:
        s_jobs, s_probs = fetch_all(startups, source_type="startup")
        jobs.extend(s_jobs)
        problems.extend(s_probs)
    return jobs, problems

