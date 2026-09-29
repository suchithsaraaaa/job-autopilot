"""Tailor the resume to a job description without inventing anything.

The LLM is only allowed to (a) pick and order bullet ids and skill names that
already exist in config/resume.yaml and (b) write a two-sentence summary. The
summary is rejected if it contains a number that is not in the resume. Bullet
text is never rewritten, so it cannot drift from what you actually did.
Without an API key (or on any failure) a deterministic keyword tailor is used.
"""
import json
import logging
import os
import re

from . import keywords as kw

log = logging.getLogger(__name__)
MAX_BULLETS_PER_ROLE = 4
MAX_BULLETS_FOR_COVERAGE = 6   # a role may grow to this to carry JD keywords
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
_WORD = re.compile(r"[a-z0-9+#.]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _all_skills(resume: dict) -> list[str]:
    return [s for group in resume["skills"].values() for s in group]


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text))


def resume_numbers(resume: dict) -> set[str]:
    blob = json.dumps(resume, default=str)
    return _numbers(blob)


def deterministic(resume: dict, jd: str) -> dict:
    jd_tok = _tokens(jd)
    exp = []
    for role in resume["experience"]:
        scored = []
        for b in role["bullets"]:
            hit = sum(1 for t in b.get("tags", []) if any(t in w or w in t for w in jd_tok if len(w) > 2))
            hit += len(_tokens(b["text"]) & jd_tok) * 0.1
            scored.append((hit, b["id"]))
        keep = [i for _, i in sorted(scored, key=lambda x: -x[0])[:MAX_BULLETS_PER_ROLE]]
        # keep original order among the chosen bullets
        order = [b["id"] for b in role["bullets"] if b["id"] in keep]
        exp.append({"id": role["id"], "bullet_ids": order})
    skills = _all_skills(resume)
    skills.sort(key=lambda s: 0 if kw.present_in(s, jd) else 1)
    return {"summary": resume["summary"].strip(), "experience": exp, "skills_order": skills,
            "gaps": [], "method": "keywords"}


def finalize(resume: dict, t: dict, jd: str) -> dict:
    """Pull in every truthful JD keyword, then record what is covered and what is a real gap."""
    words = kw.jd_keywords(jd, resume)
    kw.cover_more(resume, t, words, MAX_BULLETS_FOR_COVERAGE)
    cov = kw.coverage(resume, t, words)
    t["jd_keywords"], t["keywords_matched"] = words, cov["covered"]
    t["gaps"] = cov["gaps"][:8]        # asked for by the JD, absent from your resume
    return t


PROMPT = """You tailor a candidate's resume to a job description. You may ONLY choose from
the facts provided; never add employers, skills, tools, degrees or numbers.

Return a single JSON object, nothing else:
{{"summary": "<=2 sentences, plain, no buzzwords, mentions only facts in the resume",
 "experience": [{{"id": "<role id>", "bullet_ids": ["<bullet id>", ...]}}],
 "skills_order": ["<skill from the list, most relevant to this job first>", ...],
 "gaps": ["<up to 5 things the JD asks for that the resume does NOT show>"]}}

Rules: at most {maxb} bullets per role, most relevant first; include every role id;
skills_order must use only skill names from SKILLS; keep the summary honest about seniority
(the candidate is early-career).

RESUME FACTS (JSON):
{resume}

SKILLS: {skills}

JD KEYWORDS (use those that are true of the resume in the summary, and prefer bullets containing them): {kws}

JOB: {title} at {company}
JOB DESCRIPTION:
{jd}
"""


def _validate(out: dict, resume: dict) -> dict:
    roles = {r["id"]: {b["id"] for b in r["bullets"]} for r in resume["experience"]}
    skills = set(_all_skills(resume))
    exp, seen = [], set()
    for r in out.get("experience", []):
        if r.get("id") in roles and r["id"] not in seen:
            seen.add(r["id"])
            ids = [i for i in r.get("bullet_ids", []) if i in roles[r["id"]]][:MAX_BULLETS_PER_ROLE]
            exp.append({"id": r["id"], "bullet_ids": ids})
    for rid in roles:  # any role the model dropped keeps its bullets in file order
        if rid not in seen:
            role = next(x for x in resume["experience"] if x["id"] == rid)
            exp.append({"id": rid, "bullet_ids": [b["id"] for b in role["bullets"]][:MAX_BULLETS_PER_ROLE]})
    order = {r["id"]: i for i, r in enumerate(resume["experience"])}
    exp.sort(key=lambda r: order[r["id"]])  # roles stay in the resume's own order
    summary = str(out.get("summary", "")).strip()
    if not summary or len(summary) > 400 or not _numbers(summary) <= resume_numbers(resume):
        raise ValueError("summary failed validation")
    sk = [s for s in out.get("skills_order", []) if s in skills]
    sk += [s for s in _all_skills(resume) if s not in sk]
    return {"summary": summary, "experience": exp, "skills_order": sk,
            "gaps": [str(g) for g in out.get("gaps", [])][:5], "method": "llm"}


def tailor(resume: dict, job, use_llm: bool = True) -> dict:
    jd = f"{job.title}\n{job.description}"
    base = finalize(resume, deterministic(resume, jd), jd)
    if not (use_llm and os.environ.get("ANTHROPIC_API_KEY")):
        return base
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=MODEL, max_tokens=1500,
            messages=[{"role": "user", "content": PROMPT.format(
                maxb=MAX_BULLETS_PER_ROLE, resume=json.dumps(
                    {k: resume[k] for k in ("summary", "experience", "projects", "education")}, default=str),
                skills=_all_skills(resume), kws=kw.jd_keywords(job.description, resume), title=job.title, company=job.company,
                jd=job.description[:9000])}])
        text = msg.content[0].text
        out = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return finalize(resume, _validate(out, resume), f"{job.title}\n{job.description}")
    except Exception as e:
        log.warning("LLM tailoring failed for %s (%s); using keyword tailoring", job.id, e)
        return base
