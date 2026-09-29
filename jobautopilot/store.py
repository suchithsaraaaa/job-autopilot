"""Remembers which postings were already handled, so you never get duplicates."""
import json
from datetime import datetime, timezone

from .config import ROOT

PATH = ROOT / "data" / "state.json"


def load() -> dict:
    if PATH.exists():
        return json.loads(PATH.read_text())
    return {"jobs": {}}


def save(state: dict) -> None:
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(state, indent=1, sort_keys=True))


def mark(state: dict, job, status: str, **extra) -> None:
    state["jobs"][job.id] = {
        "company": job.company, "title": job.title, "url": job.url, "status": status,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra,
    }


def seen(state: dict, job) -> bool:
    return job.id in state["jobs"]
