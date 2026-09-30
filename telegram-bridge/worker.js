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

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Job Autopilot Telegram Bridge is active.", { status: 200 });
    }

    // 1. Verify Webhook Secret (if configured)
    if (env.TELEGRAM_WEBHOOK_SECRET) {
      const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (secret !== env.TELEGRAM_WEBHOOK_SECRET) {
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
    if (chatId !== allowedChatId) {
      return new Response(JSON.stringify({ status: "unauthorized" }), { status: 200 });
    }

    const text = message.text.trim();
    const cmd = text.split(/\s+/)[0].toLowerCase();
    const repo = env.GITHUB_REPOSITORY || DEFAULT_REPO;
    const workflow = DEFAULT_WORKFLOW;

    // Helper to send message to Telegram
    const replyTelegram = async (msg) => {
      const tgUrl = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
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
        const res = await fetch(url, { headers });
        if (res.ok) {
          const data = await res.json();
          if (data.total_count > 0) return true;
        }
      }
      return false;
    };

    // Helper to dispatch GitHub Actions workflow
    const dispatch = async (inputs) => {
      const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Accept": "application/vnd.github+json",
          "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
          "Content-Type": "application/json",
          "User-Agent": "job-autopilot-worker",
        },
        body: JSON.stringify({ ref: "main", inputs }),
      });
      return res.ok;
    };

    // 3. Command Routing
    if (cmd === "/start" || cmd === "/run") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.");
        return new Response(JSON.stringify({ status: "concurrency_blocked" }), { status: 200 });
      }

      await replyTelegram(
        "🚀 <b>Job Autopilot started.</b>\n\n" +
        "Searching:\n" +
        "• Full-time roles\n" +
        "• Internships\n" +
        "• Startup roles\n\n" +
        "I'll send the matching jobs and tailored resumes here when the run completes."
      );
      await dispatch({ dry_run: false, trigger_source: "telegram", categories: "all" });
      return new Response(JSON.stringify({ status: "dispatched", categories: "all" }), { status: 200 });
    }

    if (cmd === "/jobs") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.");
        return new Response(JSON.stringify({ status: "concurrency_blocked" }), { status: 200 });
      }

      await replyTelegram("💼 <b>Searching full-time roles...</b>\n\nI'll send matching jobs and tailored resumes when complete.");
      await dispatch({ dry_run: false, trigger_source: "telegram", categories: "full_time" });
      return new Response(JSON.stringify({ status: "dispatched", categories: "full_time" }), { status: 200 });
    }

    if (cmd === "/internships") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.");
        return new Response(JSON.stringify({ status: "concurrency_blocked" }), { status: 200 });
      }

      await replyTelegram("🎓 <b>Searching internships...</b>\n\nI'll send matching roles and tailored resumes when complete.");
      await dispatch({ dry_run: false, trigger_source: "telegram", categories: "internship" });
      return new Response(JSON.stringify({ status: "dispatched", categories: "internship" }), { status: 200 });
    }

    if (cmd === "/startups") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.");
        return new Response(JSON.stringify({ status: "concurrency_blocked" }), { status: 200 });
      }

      await replyTelegram("🚀 <b>Searching startup opportunities...</b>\n\nI'll send matching roles and tailored resumes when complete.");
      await dispatch({ dry_run: false, trigger_source: "telegram", categories: "startup" });
      return new Response(JSON.stringify({ status: "dispatched", categories: "startup" }), { status: 200 });
    }

    if (cmd === "/dryrun") {
      if (await hasActiveRun()) {
        await replyTelegram("⏳ A job search is already running.\n\nI'll let the current run finish before starting another one.");
        return new Response(JSON.stringify({ status: "concurrency_blocked" }), { status: 200 });
      }

      await replyTelegram("🔍 <b>Running dry-run search...</b>\n\nMatches and resumes will be produced in the Actions run artifacts without sending Telegram cards.");
      await dispatch({ dry_run: true, trigger_source: "telegram", categories: "all" });
      return new Response(JSON.stringify({ status: "dispatched", dry_run: true }), { status: 200 });
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
