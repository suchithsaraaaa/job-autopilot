# Telegram Webhook Bridge for Job Autopilot

This bridge connects your Telegram bot directly to the GitHub Actions workflow in `suchithsaraaaa/job-autopilot`.

When you press **Start** (`/start`) in your Telegram bot, the bridge immediately acknowledges your message on Telegram and dispatches the GitHub Actions `job-search.yml` workflow with `trigger_source=telegram` and `categories=all`.

The complete job search, filtering, scoring, one-page resume generation, and Telegram notifications run automatically in GitHub Actions.

---

## Architecture

```text
You (Telegram)
      │
      ▼  /start, /jobs, /internships, /startups, /dryrun
┌────────────────────────────────────────────────────────┐
│  Serverless Telegram Bridge (Cloudflare Worker / Py)   │
│  - Verifies Telegram secret token header               │
│  - Verifies allowed chat ID (rejects unauthorized)     │
│  - Checks for active in-progress runs (concurrency)    │
│  - Sends instant acknowledgement back to Telegram      │
│  - Dispatches GitHub Actions workflow_dispatch API     │
└────────────────────────────────────────────────────────┘
      │
      ▼
┌────────────────────────────────────────────────────────┐
│  GitHub Actions: job-search.yml                        │
│  - Fetch verified companies + startups                 │
│  - Classify full-time / internship / startup           │
│  - Score & verify 2027 student eligibility             │
│  - Tailor truthful, single-page PDF resumes            │
│  - Send formatted job cards & PDFs to your Telegram    │
└────────────────────────────────────────────────────────┘
```

---

## Option A (Recommended): 24/7 Cloudflare Worker (100% Free, Zero Server)

Cloudflare Workers run 24/7 on Cloudflare's global edge network at zero cost. Your computer can be turned off completely.

### 1. Create the Worker

1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com/) (free account).
2. Go to **Workers & Pages** -> **Create Application** -> **Create Worker**.
3. Name it `job-autopilot-bridge`.
4. Click **Deploy**.
5. Click **Edit code**, replace all contents with the code from [`telegram-bridge/worker.js`](./worker.js), and click **Save and Deploy**.

### 2. Set Environment Variables / Secrets

In your Worker page, go to **Settings** -> **Variables and Secrets**:

| Variable Name | Description | Value |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | e.g. `8552987907:AAE...` |
| `TELEGRAM_CHAT_ID` | Your Telegram Chat ID | e.g. `8552987907` |
| `GITHUB_TOKEN` | Fine-Grained GitHub PAT with Actions Read & Write permission | `github_pat_...` |
| `GITHUB_REPOSITORY` | Repository name | `suchithsaraaaa/job-autopilot` |
| `GITHUB_BRANCH` | Default branch | `main` |
| `TELEGRAM_WEBHOOK_SECRET` | Secret string for webhook security | Any random token (e.g. `random_secret_xyz`) |

### 3. Register Webhook with Telegram

Open your terminal or browser and send this one-time request:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://job-autopilot-bridge.<your-subdomain>.workers.dev",
    "secret_token": "<YOUR_TELEGRAM_WEBHOOK_SECRET>"
  }'
```

Telegram will respond:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

---

## Option B: Lightweight Python Webhook Server

If you prefer to run the bridge on an EC2 instance, VPS, or local server:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export GITHUB_TOKEN="your_github_token"
export TELEGRAM_WEBHOOK_SECRET="your_webhook_secret"

python -c "from jobautopilot import webhook; webhook.serve_webhook(port=8080)"
```

---

## Telegram Commands Supported

- `/start` or `/run`: Full automated run (Full-time + Internships + Startups).
- `/jobs`: Search full-time positions only.
- `/internships`: Search internship & student roles only.
- `/startups`: Search curated startups only.
- `/dryrun`: Run search & generate resumes as GitHub Action artifacts without sending cards.
- `/help`: Display all commands.

---

## Security Model

1. **No Credentials in Code**: All tokens are read from environment variables.
2. **Webhook Verification**: Validates `X-Telegram-Bot-Api-Secret-Token` on every request.
3. **Sender Authorization**: Non-matching chat IDs are rejected with a harmless 200 (prevents Telegram retry loops while ignoring unauthorized messages).
4. **Concurrency Guard**: If a GitHub Actions run is already `queued` or `in_progress`, the bridge notifies you and prevents duplicate execution.
5. **Token Redaction**: Any Telegram or GitHub error message masks sensitive credentials (`[REDACTED]`).
