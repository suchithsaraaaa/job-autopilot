/**
 * Cloudflare Worker: Telegram Webhook Bridge for Job Autopilot
 *
 * Runs 24/7 serverless with 0 cost.
 * Bridges Telegram /start command directly to GitHub Actions workflow_dispatch.
 *
 * Required Environment Variables (set in Cloudflare Worker Settings -> Variables):
 * - TELEGRAM_BOT_TOKEN: Your Telegram bot token
 * - TELEGRAM_CHAT_ID: Your personal numerical chat ID
 * - GITHUB_TOKEN: GitHub Fine-Grained Personal Access Token with Actions Read & Write permission
 * - TELEGRAM_WEBHOOK_SECRET (optional): Secret token configured with setWebhook
 * - GITHUB_REPOSITORY (optional, defaults to "suchithsaraaaa/job-autopilot")
 */

const DEFAULT_REPO = "suchithsaraaaa/job-autopilot";
const DEFAULT_WORKFLOW = "job-search.yml";

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function sanitize(text, ...secrets) {
  if (!text) return "";
  let clean = String(text);
  for (const s of secrets) {
    if (s && String(s).length > 3) {
      clean = clean.split(String(s)).join("[REDACTED]");
    }
  }
  clean = clean.replace(/bot\d+:[A-Za-z0-9_-]+/g, "bot[REDACTED]");
  clean = clean.replace(/ghp_[A-Za-z0-9_]{20,}/g, "ghp_[REDACTED]");
  clean = clean.replace(/github_pat_[A-Za-z0-9_]{20,}/g, "github_pat_[REDACTED]");
  clean = clean.replace(/Bearer\s+[A-Za-z0-9_\-\.]{15,}/g, "Bearer [REDACTED]");
  return clean;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Job Autopilot Telegram Bridge is active.", { status: 200 });
    }

    // 1. Verify Webhook Secret (if configured)
    if (env.TELEGRAM_WEBHOOK_SECRET) {
      const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (secret !== env.TELEGRAM_WEBHOOK_SECRET) {
        console.warn("[telegram-bridge] Unauthorized webhook secret token");
        return new Response(JSON.stringify({ error: "Unauthorized webhook" }), { status: 403 });
      }
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response(JSON.stringify({ error: "Invalid JSON" }), { status: 400 });
    }

    const message = update.message || update.edited_message;
    if (!message || !message.text) {
      return new Response(JSON.stringify({ status: "ignored" }), { status: 200 });
    }

    const chatId = String(message.chat.id);
    const allowedChatId = String(env.TELEGRAM_ALLOWED_CHAT_ID || env.TELEGRAM_CHAT_ID || "");

    // 2. Reject unauthorized Telegram users
    if (!allowedChatId || chatId !== allowedChatId) {
      console.warn(`[telegram-bridge] Unauthorized chat attempt from ID: ${chatId}`);
      return new Response(JSON.stringify({ status: "unauthorized" }), { status: 200 });
    }

    const text = message.text.trim();
    const cmd = text.split(/\s+/)[0].toLowerCase();
    const repo = env.GITHUB_REPOSITORY || DEFAULT_REPO;
    const workflow = DEFAULT_WORKFLOW;
    const ref = env.GITHUB_BRANCH || env.GITHUB_REF || "main";

    console.log(`[telegram-bridge] Received command '${cmd}' from authorized chat ${chatId}`);

    // Helper to send message to Telegram
    const replyTelegram = async (msg) => {
      const tgUrl = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
      try {
        await fetch(tgUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chatId,
            text: msg,
            parse_mode: "HTML",
            disable_web_page_preview: true,
          }),
        });
      } catch (err) {
        console.error(`[telegram-bridge] Failed to send Telegram message: ${sanitize(String(err), env.TELEGRAM_BOT_TOKEN)}`);
      }
    };

    // Helper to check active GitHub Actions runs (concurrency check)
    const hasActiveRun = async () => {
      const headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "User-Agent": "job-autopilot-worker",
      };
      for (const status of ["in_progress", "queued"]) {
        const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/runs?status=${status}`;
        try {
          const res = await fetch(url, { headers });
          if (res.ok) {
            const data = await res.json();
            if (data.total_count > 0) {
              console.log(`[telegram-bridge] Active run found with status '${status}' (count=${data.total_count})`);
              return true;
            }
          } else {
            console.warn(`[telegram-bridge] Failed checking run status ${status}: HTTP ${res.status}`);
          }
        } catch (err) {
          console.warn(`[telegram-bridge] Error checking run status ${status}: ${sanitize(String(err), env.GITHUB_TOKEN)}`);
        }
      }
      return false;
    };

    // Helper to dispatch GitHub Actions workflow
    const dispatch = async (inputs) => {
      const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
      console.log(`[telegram-bridge] Dispatching workflow '${workflow}' (ref: ${ref}, repo: ${repo})`);
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: {
            "Accept": "application/vnd.github+json",
            "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
            "Content-Type": "application/json",
            "User-Agent": "job-autopilot-worker",
          },
          body: JSON.stringify({ ref, inputs }),
        });
        console.log(`[telegram-bridge] GitHub dispatch response HTTP status: ${res.status}`);
        if (res.status === 204 || res.status === 200) {
          return { ok: true, status: res.status };
        }
        let detail = "";
        try {
          const body = await res.json();
          detail = body.message || JSON.stringify(body);
        } catch {
          detail = await res.text();
        }
        const cleanDetail = sanitize(detail, env.GITHUB_TOKEN, env.TELEGRAM_BOT_TOKEN);
        console.error(`[telegram-bridge] GitHub dispatch failed: HTTP ${res.status} - ${cleanDetail}`);
        return { ok: false, status: res.status, error: `GitHub API error (HTTP ${res.status}): ${cleanDetail}` };
      } catch (err) {
        const cleanErr = sanitize(String(err), env.GITHUB_TOKEN, env.TELEGRAM_BOT_TOKEN);
        console.error(`[telegram-bridge] GitHub dispatch exception: ${cleanErr}`);
        return { ok: false, status: 500, error: `Dispatch request failed: ${cleanErr}` };
      }
    };

    // 3. Command Routing
    if (cmd === "/start" || cmd === "/run") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running. Results from that run will be sent when it finishes.");
        return new Response(JSON.stringify({ status: "already_running" }), { status: 200 });
      }

      await replyTelegram(
        "🚀 <b>Job search started.</b>\n" +
        "Searching full-time, internship and startup roles.\n" +
        "I'll send the results when the search finishes."
      );
      const res = await dispatch({ dry_run: false, trigger_source: "telegram", categories: "all" });
      if (res.ok) {
        await replyTelegram("✅ <b>Search queued successfully.</b>");
        return new Response(JSON.stringify({ status: "dispatched", categories: "all" }), { status: 200 });
      } else {
        await replyTelegram(`⚠️ <b>Failed to start job search workflow.</b>\n${escapeHtml(res.error)}`);
        return new Response(JSON.stringify({ status: "dispatch_failed", detail: res.error }), { status: 500 });
      }
    }

    if (cmd === "/jobs") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running. Results from that run will be sent when it finishes.");
        return new Response(JSON.stringify({ status: "already_running" }), { status: 200 });
      }

      await replyTelegram("💼 <b>Searching full-time roles...</b>\n\nI'll send matching jobs and tailored resumes when complete.");
      const res = await dispatch({ dry_run: false, trigger_source: "telegram", categories: "full_time" });
      if (res.ok) {
        await replyTelegram("✅ <b>Search queued successfully.</b>");
        return new Response(JSON.stringify({ status: "dispatched", categories: "full_time" }), { status: 200 });
      } else {
        await replyTelegram(`⚠️ <b>Failed to start job search workflow.</b>\n${escapeHtml(res.error)}`);
        return new Response(JSON.stringify({ status: "dispatch_failed", detail: res.error }), { status: 500 });
      }
    }

    if (cmd === "/internships") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running. Results from that run will be sent when it finishes.");
        return new Response(JSON.stringify({ status: "already_running" }), { status: 200 });
      }

      await replyTelegram("🎓 <b>Searching internships...</b>\n\nI'll send matching roles and tailored resumes when complete.");
      const res = await dispatch({ dry_run: false, trigger_source: "telegram", categories: "internship" });
      if (res.ok) {
        await replyTelegram("✅ <b>Search queued successfully.</b>");
        return new Response(JSON.stringify({ status: "dispatched", categories: "internship" }), { status: 200 });
      } else {
        await replyTelegram(`⚠️ <b>Failed to start job search workflow.</b>\n${escapeHtml(res.error)}`);
        return new Response(JSON.stringify({ status: "dispatch_failed", detail: res.error }), { status: 500 });
      }
    }

    if (cmd === "/startups") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running. Results from that run will be sent when it finishes.");
        return new Response(JSON.stringify({ status: "already_running" }), { status: 200 });
      }

      await replyTelegram("🚀 <b>Searching startup opportunities...</b>\n\nI'll send matching roles and tailored resumes when complete.");
      const res = await dispatch({ dry_run: false, trigger_source: "telegram", categories: "startup" });
      if (res.ok) {
        await replyTelegram("✅ <b>Search queued successfully.</b>");
        return new Response(JSON.stringify({ status: "dispatched", categories: "startup" }), { status: 200 });
      } else {
        await replyTelegram(`⚠️ <b>Failed to start job search workflow.</b>\n${escapeHtml(res.error)}`);
        return new Response(JSON.stringify({ status: "dispatch_failed", detail: res.error }), { status: 500 });
      }
    }

    if (cmd === "/dryrun") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running. Results from that run will be sent when it finishes.");
        return new Response(JSON.stringify({ status: "already_running" }), { status: 200 });
      }

      await replyTelegram("🔍 <b>Running dry-run search...</b>\n\nMatches and resumes will be produced in the Actions run artifacts without sending Telegram cards.");
      const res = await dispatch({ dry_run: true, trigger_source: "telegram", categories: "all" });
      if (res.ok) {
        await replyTelegram("✅ <b>Search queued successfully.</b>");
        return new Response(JSON.stringify({ status: "dispatched", categories: "all", dry_run: true }), { status: 200 });
      } else {
        await replyTelegram(`⚠️ <b>Failed to start job search workflow.</b>\n${escapeHtml(res.error)}`);
        return new Response(JSON.stringify({ status: "dispatch_failed", detail: res.error }), { status: 500 });
      }
    }

    if (cmd === "/help") {
      await replyTelegram(
        "🤖 <b>Job Autopilot Commands:</b>\n\n" +
        "/start - Full search (Full-time + Internships + Startups)\n" +
        "/jobs - Search full-time roles only\n" +
        "/internships - Search internships only\n" +
        "/startups - Search startup opportunities only\n" +
        "/dryrun - Test run without sending notifications\n" +
        "/help - Show this guide"
      );
      return new Response(JSON.stringify({ status: "help_sent" }), { status: 200 });
    }

    await replyTelegram("Press /start to run a job search or /help to view commands.");
    return new Response(JSON.stringify({ status: "prompted" }), { status: 200 });
  },
};
