import argparse
import logging
import os
from collections import Counter
from pathlib import Path

from . import config, legit, match as matcher, notify, render, sources, store, tailor

log = logging.getLogger("jobautopilot")
OUT = config.ROOT / "out"


def run(args) -> int:
    prof, comps, resume = config.profile(), config.companies(), config.resume()
    st_comps = config.startups()
    by_name = {c["name"]: c for c in comps + st_comps}
    tg = notify.Telegram()
    dry = args.dry_run or not tg.enabled
    if not tg.enabled:
        log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID): printing instead")

    req_cats = getattr(args, "categories", None) or os.environ.get("JOB_CATEGORIES") or "all"
    trig_src = getattr(args, "trigger_source", None) or os.environ.get("TRIGGER_SOURCE") or "manual"

    if req_cats == "startup":
        jobs, problems = sources.fetch_all(st_comps, source_type="startup")
        sources_searched = st_comps
    elif req_cats == "full_time":
        jobs, problems = sources.fetch_all(comps, source_type="company")
        sources_searched = comps
    else:  # "all" or "internship"
        jobs, problems = sources.fetch_everything(comps, st_comps)
        sources_searched = comps + st_comps

    state = store.load()
    fresh = [j for j in jobs if not store.seen(state, j)]
    seen_count = len(jobs) - len(fresh)
    log.info("%d postings fetched (%s, %s), %d previously seen, %d new",
             len(jobs), trig_src, req_cats, seen_count, len(fresh))

    passed, rejected = [], Counter()
    for j in fresh:
        c_meta = by_name.get(j.company, {"name": j.company, "ats": j.ats})
        ok, why = legit.check(j, c_meta)
        if not ok:
            store.mark(state, j, "blocked-legitimacy", reasons=why)
            rejected["legitimacy"] += 1
            continue
        m = matcher.evaluate(j, prof)
        if not m.ok:
            store.mark(state, j, "rejected", reasons=m.reasons)
            rejected[m.reasons[0].split(":")[0].split(" (")[0]] += 1
            continue

        # Category constraint filtering
        if req_cats == "internship" and "internship" not in m.categories:
            continue
        if req_cats == "startup" and "startup" not in m.categories:
            continue
        if req_cats == "full_time" and "internship" in m.categories:
            continue

        passed.append((m.score, j, m))
    passed.sort(key=lambda x: -x[0])
    batch, later = passed[: prof.get("max_notify_per_run", 12)], passed[prof.get("max_notify_per_run", 12):]
    log.info("%d matched, %d rejected (%s), sending %d now, %d held for next run",
             len(passed), sum(rejected.values()), dict(rejected), len(batch), len(later))

    applied = needs = 0
    for score, j, m in batch:
        t = tailor.tailor(resume, j, use_llm=not args.no_llm)
        pdf = render.build_pdf(resume, t, OUT / f"Suchith_Sara_{render.slug(j.company)}_{render.slug(j.title)}.pdf")
        status_line, status = "Tap to open the posting, resume attached.", "notified"

        if prof["apply"].get("auto_apply") and not dry:
            from . import apply as applier
            res = applier.apply(j, pdf, prof["apply"]["answers"], submit=prof["apply"].get("submit", False), out_dir=OUT)
            if res.status == "submitted":
                status_line, status, applied = "✅ Applied automatically.", "applied", applied + 1
            elif res.status == "filled":
                status_line, status = f"Form pre-filled (dry run). {res.detail}", "filled"
            else:
                status_line, status, needs = f"Needs you: {res.detail}", "needs-human", needs + 1

        card = notify.job_card(j, m, status_line=status_line, gaps=t.get("gaps"),
                               coverage=(len(t["keywords_matched"]), len(t["jd_keywords"])))
        if dry:
            print(f"\n[{score}] {j.company} | {j.title} | {j.location}\n    {j.url}\n    resume: {pdf.name} ({t['method']})")
        else:
            try:
                tg.document(pdf, card, ("Open & apply", j.apply_url or j.url))
            except Exception as e:
                log.error("Telegram send failed for %s: %s", j.id, e)
                continue  # not marked seen, so it is retried next run
        store.mark(state, j, status, score=score)

    if not dry or args.save_state:
        store.save(state)
    if not dry:
        summary_lines = [
            "🔎 <b>Job search complete</b>\n",
            f"Scanned: {len(jobs)} postings ({seen_count} previously seen)",
            f"New postings: {len(fresh)}",
            f"Matched: {len(passed)}",
            f"Sent: {len(batch)}",
        ]
        if len(passed) == 0:
            summary_lines.append("\nNo new matching jobs were found.")
        elif later:
            summary_lines.append(f"\n{len(later)} more held for the next run")

        if applied or needs:
            summary_lines.append(f"Auto-applied: {applied}, Needs you: {needs}")
        if problems:
            summary_lines.append(f"\n⚠️ {len(problems)} boards failed to resolve (check slugs)")

        try:
            tg.message("\n".join(summary_lines))
        except Exception as e:
            log.error("Failed to send Telegram summary message: %s", e)
    for p in problems:
        log.warning("board problem: %s", p)
    return 0


def check_companies(args) -> int:
    _, problems = sources.fetch_all(config.companies())
    print("All company boards resolved." if not problems else "\n".join(problems))
    return 1 if problems else 0


def check_startups(args) -> int:
    _, problems = sources.fetch_all(config.startups(), source_type="startup")
    print("All startup boards resolved." if not problems else "\n".join(problems))
    return 1 if problems else 0


def test_notify(args) -> int:
    tg = notify.Telegram()
    if not tg.enabled:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first.")
        return 1
    tg.message("✅ job-autopilot can reach your phone.")
    print("Sent.")
    return 0


def demo(args) -> int:
    """Render a tailored resume for a sample JD; needs no network or keys."""
    from .models import Job
    jd = Path(args.jd).read_text() if args.jd else (
        "AI Engineer. Build RAG pipelines and serve LLMs with vLLM. Python, Qdrant, embeddings, AWS.")
    job = Job("demo:x:1", "demo", "DemoCo", "AI Engineer", "Hyderabad", "https://example.com", "", jd)
    resume = config.resume()
    t = tailor.tailor(resume, job, use_llm=not args.no_llm)
    out = render.build_pdf(resume, t, OUT / "demo_resume.pdf")
    print(f"Wrote {out} ({t['method']}); JD keywords covered: {t['keywords_matched']}; real gaps: {t['gaps']}")
    return 0


def cli(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jobautopilot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="search, filter, tailor, notify")
    r.add_argument("--dry-run", action="store_true", help="print matches, send nothing, remember nothing")
    r.add_argument("--no-llm", action="store_true", help="keyword tailoring only")
    r.add_argument("--save-state", action="store_true", help="with --dry-run, still record seen jobs")
    r.add_argument("--categories", choices=["all", "full_time", "internship", "startup"], default="all",
                   help="job categories to search: all, full_time, internship, startup")
    r.add_argument("--trigger-source", default="manual",
                   help="source triggering the workflow (manual, telegram, schedule)")
    r.set_defaults(fn=run)
    sub.add_parser("check-companies").set_defaults(fn=check_companies)
    sub.add_parser("check-startups").set_defaults(fn=check_startups)
    sub.add_parser("test-notify").set_defaults(fn=test_notify)
    d = sub.add_parser("demo")
    d.add_argument("--jd", help="path to a job description text file")
    d.add_argument("--no-llm", action="store_true")
    d.set_defaults(fn=demo)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(cli())
