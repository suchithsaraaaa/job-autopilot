"""OPTIONAL auto-apply for Greenhouse and Lever forms, using Playwright.

Off by default (profile.yaml -> apply.auto_apply). It is deliberately cautious:
it fills only the standard fields, refuses to submit if ANY required field is
left empty (custom questions, work-authorisation, etc.) or a captcha is
present, and in that case hands the job back to you on Telegram. With
apply.submit: false it fills the form, takes a screenshot and stops.

Not every site allows automation; you are responsible for complying with the
terms of the boards you enable. Form markup changes, so treat this as
best-effort and check the first few results by hand.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Result:
    status: str          # "submitted" | "filled" | "needs_human" | "error"
    detail: str = ""
    screenshot: Path | None = None


def _selectors(ats: str) -> dict:
    if ats == "greenhouse":
        return {"first": "#first_name", "last": "#last_name", "email": "#email", "phone": "#phone",
                "resume": "input[type=file]#resume, input[type=file][name*=resume]", "submit": "#submit_app, button[type=submit]"}
    return {"first": None, "name": "input[name=name]", "email": "input[name=email]", "phone": "input[name=phone]",
            "org": "input[name='org']", "linkedin": "input[name='urls[LinkedIn]']", "github": "input[name='urls[GitHub]']",
            "resume": "input[type=file][name=resume]", "submit": "button[type=submit], #btn-submit"}


def apply(job, resume_pdf: Path, answers: dict, *, submit: bool, out_dir: Path) -> Result:
    if job.ats not in ("greenhouse", "lever"):
        return Result("needs_human", f"auto-apply not supported for {job.ats}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return Result("error", "playwright not installed (pip install -r requirements-apply.txt)")

    sel = _selectors(job.ats)
    url = job.apply_url if job.ats == "greenhouse" else job.apply_url.rstrip("/")
    if job.ats == "lever" and not url.endswith("/apply"):
        url += "/apply"
    shot = out_dir / f"{job.id.replace(':', '_')}.png"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            if page.query_selector("iframe[src*='captcha'], iframe[src*='recaptcha'], .h-captcha, .g-recaptcha"):
                return Result("needs_human", "captcha on the form")
            full = f"{answers['first_name']} {answers['last_name']}"
            fills = {"first": answers["first_name"], "last": answers["last_name"], "name": full,
                     "email": answers["email"], "phone": answers["phone"], "linkedin": answers.get("linkedin", ""),
                     "github": answers.get("github", "")}
            for key, value in fills.items():
                if sel.get(key) and value and page.query_selector(sel[key]):
                    page.fill(sel[key], value)
            up = page.query_selector(sel["resume"])
            if not up:
                return Result("needs_human", "resume upload field not found")
            up.set_input_files(str(resume_pdf))

            empty = page.evaluate("""() => [...document.querySelectorAll('input[required],textarea[required],select[required]')]
                .filter(e => e.type !== 'file' && e.type !== 'hidden' && !e.value &&
                        !(e.type === 'checkbox' && e.checked)).map(e => e.name || e.id || e.type)""")
            page.screenshot(path=str(shot), full_page=True)
            if empty:
                return Result("needs_human", "required questions left: " + ", ".join(empty[:6]), shot)
            if not submit:
                return Result("filled", "form filled; submit is off (dry run)", shot)
            page.click(sel["submit"])
            page.wait_for_timeout(5000)
            body = page.inner_text("body").lower()
            if any(w in body for w in ("thank you", "application submitted", "received your application")):
                return Result("submitted", "confirmation text seen", shot)
            return Result("needs_human", "clicked submit but saw no confirmation, check manually", shot)
        except Exception as e:
            return Result("error", str(e)[:200], shot if shot.exists() else None)
        finally:
            browser.close()
