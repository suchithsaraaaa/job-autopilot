import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from . import config, legit, match as matcher, notify, render, sources, store, tailor

log = logging.getLogger("jobautopilot")
OUT = config.ROOT / "out"


def run(args) -> int:
    prof, comps, resume = config.profile(), config.companies(), config.resume()
    by_name = {c["name"]: c for c in comps}
    tg = notify.Telegram()
    dry = args.dry_run or not tg.enabled
    if not tg.enabled:
        log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID): printing instead")

    jobs, problems = sources.fetch_all(comps)
    state = store.load()
    fresh = [j for j in jobs if not store.seen(state, j)]
    log.info("%d postings fetched, %d new", len(jobs), len(fresh))

    passed, rejected = [], Counter()
    for j in fresh:
        ok, why = legit.check(j, by_name[j.company])
        if not ok:
            store.mark(state, j, "blocked-legitimacy", reasons=why)
            rejected["legitimacy"] += 1
            continue
        m = matcher.evaluate(j, prof)
        if not m.ok:
            store.mark(state, j, "rejected", reasons=m.reasons)
            rejected[m.reasons[0].split(":")[0].split(" (")[0]] += 1
            continue
        passed.append((m.score, j, m))
    passed.sort(key=lambda x: -x[0])
    batch, later = passed[: prof.get("max_notify_per_run", 12)], passed[prof.get("max_notify_per_run", 12):]
    log.info("%d match, sending %d now, %d held for next run", len(passed), len(batch), len(later))

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
        bits = [f"Scanned {len(jobs)} postings from {len(comps)} verified companies.",
                f"{len(fresh)} new, {len(passed)} matched, {len(batch)} sent"]
        if later:
            bits.append(f"{len(later)} more held for the next run")
        if applied or needs:
            bits.append(f"auto-applied {applied}, needs you {needs}")
        if problems:
            bits.append(f"⚠️ {len(problems)} boards failed (check slugs)")
        if batch or problems:
            tg.message("\n".join(bits))
    for p in problems:
        log.warning("board problem: %s", p)
    return 0


def check_companies(args) -> int:
    _, problems = sources.fetch_all(config.companies())
    print("All company boards resolved." if not problems else "\n".join(problems))
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
    r.set_defaults(fn=run)
    sub.add_parser("check-companies").set_defaults(fn=check_companies)
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
