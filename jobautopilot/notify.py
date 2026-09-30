"""Telegram notifications."""
import html
import os
import re

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        tok = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if tok:
            tok = tok.strip().replace(" ", "")
            if tok.endswith("Ø") or tok.endswith("ø"):
                tok = tok[:-1] + "0"
        self.token = tok

        cid = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        if cid:
            cid = str(cid).strip().replace(" ", "")
        self.chat_id = cid

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def __repr__(self) -> str:
        return f"<Telegram enabled={self.enabled}>"

    def _call(self, method: str, **kw):
        url = API.format(token=self.token, method=method)
        try:
            r = requests.post(url, timeout=60, **kw)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            msg = str(e)
            # Redact any instance of the token or bot<token> in URLs
            msg = re.sub(r"bot[^/\s]+", "bot[REDACTED]", msg)
            if self.token:
                msg = msg.replace(self.token, "[REDACTED]")
            raise RuntimeError(f"Telegram API error ({method}): {msg}") from None

    def message(self, text: str, button: tuple[str, str] | None = None):
        import json
        data = {"chat_id": self.chat_id, "text": text[:4000], "parse_mode": "HTML",
                "disable_web_page_preview": True}
        if button:
            data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": button[0], "url": button[1]}]]})
        return self._call("sendMessage", data=data)

    def document(self, path, caption: str, button: tuple[str, str] | None = None):
        import json
        data = {"chat_id": self.chat_id, "caption": caption[:1000], "parse_mode": "HTML"}
        if button:
            data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": button[0], "url": button[1]}]]})
        with open(path, "rb") as f:
            return self._call("sendDocument", data=data, files={"document": f})


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def category_badge(job, match=None) -> str:
    cats = (getattr(match, "categories", []) if match else None) or getattr(job, "categories", []) or []
    is_st = "startup" in cats or getattr(job, "source", "") == "startup"
    is_in = "internship" in cats or getattr(job, "employment_type", "") == "internship"

    if is_st and is_in:
        return "🚀 STARTUP • 🎓 INTERNSHIP"
    if is_st:
        return "🚀 STARTUP"
    if is_in:
        return "🎓 INTERNSHIP"
    return "💼 FULL-TIME"


def job_card(job, match, *, status_line: str, gaps: list[str] | None = None, coverage: tuple[int, int] | None = None) -> str:
    badge = category_badge(job, match)
    lines = [f"<b>{badge}</b>", f"<b>{esc(job.title)}</b>\n"]
    lines.append(f"Company: {esc(job.company)}")
    lines.append(f"Location: {esc(job.location or 'Location n/a')}")
    cats = (getattr(match, "categories", []) if match else None) or getattr(job, "categories", []) or []
    emp_type = "Internship" if ("internship" in cats or getattr(job, "employment_type", "") == "internship") else "Full-time"
    lines.append(f"Type: {emp_type}")
    lines.append(f"Match: {match.score}%")

    if match.hits:
        lines.append("\nWhy it matches:\n• " + "\n• ".join(esc(h) for h in match.hits[:5]))

    elig = getattr(match, "eligibility", None) or getattr(job, "eligibility", "unknown")
    if elig and elig != "unknown":
        lines.append(f"\nEligibility:\n{esc(elig)}")

    if coverage and coverage[1]:
        lines.append(f"\nResume covers {coverage[0]}/{coverage[1]} JD keywords")
    if gaps:
        lines.append("Not in your resume: " + esc(", ".join(gaps[:5])))

    lines.append(f"\n{status_line}")
    return "\n".join(lines)

