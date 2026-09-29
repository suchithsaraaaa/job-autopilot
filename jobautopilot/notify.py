"""Telegram notifications."""
import html
import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

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
            if self.token and self.token in msg:
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


def job_card(job, match, *, status_line: str, gaps: list[str] | None = None, coverage: tuple[int, int] | None = None) -> str:
    lines = [f"<b>{esc(job.title)}</b>", f"{esc(job.company)} · {esc(job.location or 'Location n/a')}",
             f"Match {match.score}/100" + (f" · {esc(', '.join(match.hits[:6]))}" if match.hits else "")]
    if coverage and coverage[1]:
        lines.append(f"Resume covers {coverage[0]}/{coverage[1]} JD keywords")
    if gaps:
        lines.append("Not in your resume: " + esc(", ".join(gaps[:5])))
    lines.append(status_line)
    return "\n".join(lines)
