"""Telegram Webhook Bridge to GitHub Actions workflow_dispatch."""
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import notify

log = logging.getLogger(__name__)

DEFAULT_REPO = "suchithsaraaaa/job-autopilot"
DEFAULT_WORKFLOW = "job-search.yml"
GITHUB_API = "https://api.github.com"


def is_authorized_chat(chat_id: int | str) -> bool:
    """Check whether the chat_id matches the allowed Telegram user."""
    allowed = (
        os.environ.get("TELEGRAM_ALLOWED_CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID")
    )
    if not allowed:
        return False
    return str(chat_id).strip() == str(allowed).strip()


def verify_webhook_secret(headers: dict[str, str]) -> bool:
    """Validate Telegram's X-Telegram-Bot-Api-Secret-Token if configured."""
    expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not expected_secret:
        return True  # If no webhook secret is configured, rely on chat_id authorization
    # Header lookup case-insensitive
    header_val = None
    for k, v in headers.items():
        if k.lower() == "x-telegram-bot-api-secret-token":
            header_val = v
            break
    return header_val == expected_secret


def check_active_github_runs(repo: str = DEFAULT_REPO, workflow: str = DEFAULT_WORKFLOW, token: str | None = None) -> bool:
    """Check if an existing run is currently queued or in_progress."""
    token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return False

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "job-autopilot-webhook/1.0",
    }
    for status in ("in_progress", "queued"):
        url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{workflow}/runs?status={status}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("total_count", 0) > 0:
                    return True
        except Exception as e:
            log.warning("Could not check workflow runs status (%s): %s", status, e)
    return False


def dispatch_github_workflow(
    inputs: dict[str, Any],
    repo: str = DEFAULT_REPO,
    workflow: str = DEFAULT_WORKFLOW,
    ref: str = "main",
    token: str | None = None,
) -> tuple[bool, str]:
    """Trigger GitHub Actions workflow_dispatch."""
    token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return False, "GITHUB_TOKEN / GH_TOKEN environment variable not set"

    url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{workflow}/dispatches"
    payload = json.dumps({"ref": ref, "inputs": inputs}).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "job-autopilot-webhook/1.0",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 204):
                return True, "Dispatched successfully"
            return False, f"Unexpected HTTP status {resp.status}"
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        return False, f"HTTPError {e.code}: {msg}"
    except Exception as e:
        return False, f"Dispatch failed: {e}"


def handle_update(update: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    """Handle incoming Telegram webhook update.

    Returns (status_code, response_dict).
    """
    headers = headers or {}
    if not verify_webhook_secret(headers):
        log.warning("Rejected webhook request: invalid secret token header")
        return 403, {"error": "Invalid webhook secret token"}

    message = update.get("message") or update.get("edited_message")
    if not message:
        return 200, {"status": "ignored_non_message"}

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not is_authorized_chat(chat_id):
        log.warning("Unauthorized user attempted to interact: %s", chat_id)
        # Return 200 to prevent Telegram from retrying, but take no action
        return 200, {"status": "unauthorized"}

    tg = notify.Telegram(chat_id=str(chat_id))
    repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    workflow = os.environ.get("GITHUB_WORKFLOW", DEFAULT_WORKFLOW)

    cmd = text.split()[0].lower() if text else ""

    if cmd in ("/start", "/run"):
        # Check concurrency
        if check_active_github_runs(repo, workflow):
            tg.message("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.")
            return 200, {"status": "concurrency_blocked"}

        tg.message(
            "🚀 <b>Job Autopilot started.</b>\n\n"
            "Searching:\n"
            "• Full-time roles\n"
            "• Internships\n"
            "• Startup roles\n\n"
            "I'll send the matching jobs and tailored resumes here when the run completes."
        )
        ok, reason = dispatch_github_workflow(
            {"dry_run": False, "trigger_source": "telegram", "categories": "all"},
            repo=repo, workflow=workflow,
        )
        if not ok:
            tg.message(f"⚠️ Failed to trigger GitHub Actions workflow: {reason}")
            return 500, {"status": "dispatch_failed", "detail": reason}
        return 200, {"status": "dispatched", "categories": "all"}

    elif cmd == "/jobs":
        if check_active_github_runs(repo, workflow):
            tg.message("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.")
            return 200, {"status": "concurrency_blocked"}

        tg.message("💼 <b>Searching full-time roles...</b>\n\nI'll send matching jobs and tailored resumes when complete.")
        ok, reason = dispatch_github_workflow(
            {"dry_run": False, "trigger_source": "telegram", "categories": "full_time"},
            repo=repo, workflow=workflow,
        )
        if not ok:
            tg.message(f"⚠️ Failed to trigger workflow: {reason}")
            return 500, {"status": "dispatch_failed", "detail": reason}
        return 200, {"status": "dispatched", "categories": "full_time"}

    elif cmd == "/internships":
        if check_active_github_runs(repo, workflow):
            tg.message("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.")
            return 200, {"status": "concurrency_blocked"}

        tg.message("🎓 <b>Searching internships...</b>\n\nI'll send matching roles and tailored resumes when complete.")
        ok, reason = dispatch_github_workflow(
            {"dry_run": False, "trigger_source": "telegram", "categories": "internship"},
            repo=repo, workflow=workflow,
        )
        if not ok:
            tg.message(f"⚠️ Failed to trigger workflow: {reason}")
            return 500, {"status": "dispatch_failed", "detail": reason}
        return 200, {"status": "dispatched", "categories": "internship"}

    elif cmd == "/startups":
        if check_active_github_runs(repo, workflow):
            tg.message("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.")
            return 200, {"status": "concurrency_blocked"}

        tg.message("🚀 <b>Searching startup opportunities...</b>\n\nI'll send matching roles and tailored resumes when complete.")
        ok, reason = dispatch_github_workflow(
            {"dry_run": False, "trigger_source": "telegram", "categories": "startup"},
            repo=repo, workflow=workflow,
        )
        if not ok:
            tg.message(f"⚠️ Failed to trigger workflow: {reason}")
            return 500, {"status": "dispatch_failed", "detail": reason}
        return 200, {"status": "dispatched", "categories": "startup"}

    elif cmd == "/dryrun":
        if check_active_github_runs(repo, workflow):
            tg.message("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.")
            return 200, {"status": "concurrency_blocked"}

        tg.message("🔍 <b>Running dry-run search...</b>\n\nMatches and resumes will be produced in the Actions run artifacts without sending Telegram cards.")
        ok, reason = dispatch_github_workflow(
            {"dry_run": True, "trigger_source": "telegram", "categories": "all"},
            repo=repo, workflow=workflow,
        )
        if not ok:
            tg.message(f"⚠️ Failed to trigger workflow: {reason}")
            return 500, {"status": "dispatch_failed", "detail": reason}
        return 200, {"status": "dispatched", "categories": "all", "dry_run": True}

    elif cmd == "/help":
        tg.message(
            "🤖 <b>Job Autopilot Commands:</b>\n\n"
            "/start - Full search (Full-time + Internships + Startups)\n"
            "/jobs - Search full-time roles only\n"
            "/internships - Search internships only\n"
            "/startups - Search startup opportunities only\n"
            "/dryrun - Test run without sending notifications\n"
            "/help - Show this guide"
        )
        return 200, {"status": "help_sent"}

    else:
        # Default or unknown command
        tg.message("Press /start to run a job search or /help to view commands.")
        return 200, {"status": "prompted"}


def serve_webhook(port: int = 8080, host: str = "0.0.0.0") -> None:
    """Run a lightweight HTTP server for receiving Telegram webhooks."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class WebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len)
            try:
                data = json.loads(post_body.decode("utf-8"))
            except Exception:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid JSON"}')
                return

            headers = {k: v for k, v in self.headers.items()}
            status, resp = handle_update(data, headers)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Job Autopilot Telegram Bridge is active.")

    server = HTTPServer((host, port), WebhookHandler)
    log.info("Starting Telegram webhook server on %s:%d", host, port)
    server.serve_forever()
