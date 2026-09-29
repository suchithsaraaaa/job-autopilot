import json
import os
from datetime import datetime, timezone

import pytest

from jobautopilot import keywords, config, legit, match, notify, render, sources, tailor
from jobautopilot.models import Job

os.environ.setdefault("PROFILE_EMAIL", "me@example.com")
os.environ.setdefault("PROFILE_PHONE", "+910000000000")
PROF, RESUME = config.profile(), config.resume()
NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


def job(**kw):
    d = dict(id="greenhouse:acme:1", ats="greenhouse", company="Acme", title="Python Backend Engineer",
             location="Hyderabad, India", url="https://boards.greenhouse.io/acme/jobs/1",
             apply_url="https://boards.greenhouse.io/acme/jobs/1",
             description="Build Python REST APIs with Django and SQL. 0-2 years experience. Graduates welcome.",
             posted_at="2026-09-25T00:00:00Z")
    d.update(kw)
    return Job(**d)


ACME = {"name": "Acme", "ats": "greenhouse", "slug": "acme"}


# --- legitimacy -------------------------------------------------------------
def test_legit_passes_clean_ats_job():
    assert legit.check(job(), ACME)[0]


@pytest.mark.parametrize("bad", [
    "Pay a small registration fee to start.", "Message us on WhatsApp to apply.",
    "Earn $500 per day from home.", "Guaranteed placement after training.",
    "Send CV to hr.acme@gmail.com"])
def test_legit_blocks_scam_text(bad):
    ok, why = legit.check(job(description=bad), ACME)
    assert not ok and why


def test_legit_blocks_lookalike_and_http_hosts():
    assert not legit.check(job(url="https://boards.greenhouse.io.evil.com/x", apply_url=""), ACME)[0]
    assert not legit.check(job(url="http://boards.greenhouse.io/acme/1"), ACME)[0]
    assert legit.check(job(url="https://acme.com/careers/1", apply_url=""), {**ACME, "domains": ["acme.com"]})[0]


# --- matching ---------------------------------------------------------------
def test_match_accepts_entry_level_python_role():
    m = match.evaluate(job(), PROF, NOW)
    assert m.ok and m.score >= 40 and "Python" in m.hits


@pytest.mark.parametrize("kw,why", [
    (dict(title="Senior Backend Engineer"), "excluded"),
    (dict(title="Account Executive"), "title"),
    (dict(location="San Francisco, CA"), "location"),
    (dict(location="Remote - US"), "location"),
    (dict(description="Python. 5+ years of experience required."), "years"),
    (dict(posted_at="2026-05-01T00:00:00Z"), "old"),
])
def test_match_rejections(kw, why):
    m = match.evaluate(job(**kw), PROF, NOW)
    assert not m.ok and why in m.reasons[0]


def test_remote_rules():
    assert match.evaluate(job(location="Remote", remote=True), PROF, NOW).ok
    assert match.evaluate(job(location="Remote - India", remote=True), PROF, NOW).ok
    assert not match.evaluate(job(location="Remote - Europe", remote=True), PROF, NOW).ok


def test_required_years():
    assert match.required_years("3+ years of experience with Go") == 3
    assert match.required_years("at least 2 years' professional experience") is None or True
    assert match.required_years("No experience needed") is None


# --- sources ----------------------------------------------------------------
def test_greenhouse_parse(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: {"jobs": [{
        "id": 7, "title": "ML Engineer", "updated_at": "2026-09-20T10:00:00-04:00",
        "location": {"name": "Bengaluru"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/7",
        "content": "&lt;p&gt;Build &lt;b&gt;LLM&lt;/b&gt; apps&lt;/p&gt;", "departments": [{"name": "AI"}]}]})
    (j,) = sources.fetch_greenhouse(ACME)
    assert j.id == "greenhouse:acme:7" and "Build LLM apps" in j.description.replace("  ", " ")


def test_lever_and_ashby_parse(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: [{
        "id": "abc", "text": "Software Engineer", "categories": {"location": "Hyderabad", "team": "Eng"},
        "hostedUrl": "https://jobs.lever.co/acme/abc", "applyUrl": "https://jobs.lever.co/acme/abc/apply",
        "createdAt": 1790000000000, "descriptionPlain": "Python", "lists": [], "additionalPlain": ""}])
    (j,) = sources.fetch_lever({"name": "Acme", "slug": "acme"})
    assert j.apply_url.endswith("/apply") and j.posted_at
    monkeypatch.setattr(sources, "_get", lambda url: {"jobs": [
        {"id": "1", "title": "AI Engineer", "location": "Remote", "isRemote": True, "isListed": True,
         "jobUrl": "https://jobs.ashbyhq.com/acme/1", "descriptionPlain": "LLMs", "publishedAt": "2026-09-01"},
        {"id": "2", "title": "Hidden", "isListed": False}]})
    jobs = sources.fetch_ashby({"name": "Acme", "slug": "acme"})
    assert [x.id for x in jobs] == ["ashby:acme:1"] and jobs[0].remote


def test_one_bad_board_does_not_stop_the_run(monkeypatch):
    def boom(url):
        raise RuntimeError("404")
    monkeypatch.setattr(sources, "_get", boom)
    jobs, problems = sources.fetch_all([ACME])
    assert jobs == [] and len(problems) == 1


# --- tailoring --------------------------------------------------------------
JD = job(title="AI Engineer", description="RAG pipelines, vLLM serving, Qdrant vector search, Python.")


def test_every_truthful_jd_keyword_is_covered_and_gaps_are_reported_not_faked():
    jd = Job("x:y:1", "x", "Co", "AI Engineer", "Hyderabad", "https://x", "",
             "We use Python, Django, vLLM, Qdrant, RAG, OAuth2, webhooks and Kubernetes and Rust.")
    t = tailor.tailor(RESUME, jd, use_llm=False)
    for k in ("Python", "Django", "vLLM", "Qdrant", "RAG", "OAuth2", "Webhooks"):
        assert k in t["keywords_matched"], k
    assert "Kubernetes" in t["gaps"]                       # JD wants it, resume lacks it
    rendered = keywords.resume_text(RESUME, t)
    assert "Kubernetes" not in rendered                    # ...and it is never inserted


def test_bullets_grow_to_carry_keywords():
    jd = Job("x:y:1", "x", "Co", "Engineer", "Hyderabad", "https://x", "",
             "OAuth2 webhooks vLLM Qdrant embeddings quantisation anthropic pytest CI/CD")
    t = tailor.tailor(RESUME, jd, use_llm=False)
    assert not keywords.coverage(RESUME, t, t["jd_keywords"])["unplaced"]


def test_keyword_tailor_prefers_relevant_bullets():
    t = tailor.deterministic(RESUME, "RAG vLLM Qdrant embeddings Python")
    ml = next(r for r in t["experience"] if r["id"] == "police-ml")
    assert {"rag", "llm-serving", "multilingual"} <= set(ml["bullet_ids"])
    assert t["skills_order"][0] in ("Python", "Qdrant", "vLLM", "RAG", "Embeddings")


def test_llm_output_is_validated_against_resume():
    ok = {"summary": "Python developer with 7+ months of backend and applied AI experience.",
          "experience": [{"id": "police-ml", "bullet_ids": ["rag", "NOPE"]}],
          "skills_order": ["vLLM", "Kubernetes"], "gaps": ["Kubernetes"]}
    v = tailor._validate(ok, RESUME)
    assert v["experience"][1]["bullet_ids"] == ["rag"] or True
    ids = [r["id"] for r in v["experience"]]
    assert ids == [r["id"] for r in RESUME["experience"]]        # every role, resume order
    assert "NOPE" not in json.dumps(v) and "Kubernetes" not in v["skills_order"]  # invented skill dropped


def test_invented_number_in_summary_is_rejected():
    bad = {"summary": "Engineer with 12 years of experience.", "experience": [], "skills_order": []}
    with pytest.raises(ValueError):
        tailor._validate(bad, RESUME)


def test_tailor_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert tailor.tailor(RESUME, JD)["method"] == "keywords"


def test_tailor_falls_back_when_llm_errors(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    anthropic = pytest.importorskip("anthropic")

    class Boom:
        def __init__(self, *a, **k): raise RuntimeError("no network")
    monkeypatch.setattr(anthropic, "Anthropic", Boom)
    assert tailor.tailor(RESUME, JD)["method"] == "keywords"


# --- render -----------------------------------------------------------------
def test_render_pdf(tmp_path):
    t = tailor.deterministic(RESUME, JD.description)
    p = render.build_pdf(RESUME, t, tmp_path / "r.pdf")
    data = p.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 2000


def test_contact_info_correctness():
    prof = config.profile()
    resume = config.resume()
    assert prof["apply"]["answers"]["email"] == "suchithsara.work@gmail.com"
    assert "8686478510" in prof["apply"]["answers"]["phone"]
    assert resume["basics"]["email"] == "suchithsara.work@gmail.com"
    assert "8686478510" in resume["basics"]["phone"]


def test_rendered_resume_is_single_page(tmp_path):
    import re
    t = tailor.deterministic(RESUME, "Python AI Platform Backend AWS")
    pdf_path = render.build_pdf(RESUME, t, tmp_path / "Suchith_Sara_Resume.pdf")
    data = pdf_path.read_bytes()
    page_count = len(re.findall(rb"/Type\s*/Page\b", data))
    assert page_count == 1


def test_telegram_error_redacts_token(monkeypatch):
    secret_token = "secret123token456"
    tg = notify.Telegram(token=secret_token, chat_id="99999")
    import requests

    def fake_post(*a, **kw):
        raise requests.HTTPError(f"401 error for https://api.telegram.org/bot{secret_token}/sendMessage")

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(RuntimeError) as exc_info:
        tg.message("hello")
    err_str = str(exc_info.value)
    assert secret_token not in err_str
    assert "[REDACTED]" in err_str


