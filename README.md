# job-autopilot

Searches verified companies for jobs that fit you, **tailors your resume to each job description**, and sends the posting plus the tailored PDF to your phone on Telegram. Optionally tries to fill the application form for you.

Runs free on GitHub Actions every 3 hours. No server, no laptop.

## How it works

1. **Search**: pulls postings straight from each company's own Greenhouse / Lever / Ashby board (`config/companies.yaml`). No aggregators, so no anonymous agencies or "consultancies".
2. **Legitimacy gate** (`jobautopilot/legit.py`): company must be on your allowlist, links must be https on the ATS or the company's own domain, and the text must not contain scam tells (fees, WhatsApp/Telegram contact, "earn $X a day", personal-email recruiters, guaranteed placement).
3. **Match** (`match.py`): title, location (India or non-region-locked remote), years of experience required (default max 2), age of posting, then a 0-100 score from your skills and entry-level signals.
4. **Tailor** (`tailor.py`, `keywords.py`): extracts the JD's keywords, then builds a resume that carries every one of them that is *true of you*: it reorders skills, picks the bullets that contain the JD's terms, and writes a two-line summary. It **never invents anything**: bullet text is never rewritten, the summary is rejected if it contains a number not in your resume, and keywords the JD wants that you don't have are reported as **gaps** on the Telegram card (never inserted). Uses Claude if `ANTHROPIC_API_KEY` is set, otherwise a keyword-based tailor; both go through the same coverage step.
5. **Notify**: one Telegram message per job: title, company, match score, "Resume covers 9/11 JD keywords", gaps, an **Open & apply** button, and the tailored PDF attached.

## Setup (10 minutes)

1. **Telegram bot**: message `@BotFather`, send `/newbot`, copy the token. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
2. **Repo secrets** (Settings → Secrets and variables → Actions): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `PROFILE_EMAIL`, `PROFILE_PHONE`, and optionally `ANTHROPIC_API_KEY` (tailoring is better with it).
3. **Edit** `config/resume.yaml` (your real facts, add your projects and LinkedIn) and `config/profile.yaml` (roles, locations, skills).
4. **Check the company slugs**: `pip install -r requirements.txt && python -m jobautopilot check-companies`. Fix or delete any that fail.
5. **Test the phone**: `TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python -m jobautopilot test-notify`.
6. **Actions tab → job-search → Run workflow** (tick *dry run* first if you want to look at matches without sending).

Preview a tailored resume for any JD without network: `python -m jobautopilot demo --jd my_jd.txt` (writes `out/demo_resume.pdf`).

## Auto-apply (optional, off by default)

Set `apply.auto_apply: true` in `config/profile.yaml`. For Greenhouse and Lever forms it fills your standard details, uploads the tailored PDF, and **only submits if `apply.submit: true` and nothing required is left blank**. Custom questions, captchas, or unsupported sites (Ashby, LinkedIn, Naukri) come to your phone as "Needs you". Start with `submit: false` and check what it fills.

Be aware: many boards forbid automated submissions, forms change, and a wrong auto-application can't be unsent. That's why the default is: you get the tailored resume and a one-tap link, and you press submit.

## Adding companies

Add a line to `config/companies.yaml` (see the comments there). Only add companies you have checked are real.

## Tests

`pip install -r requirements-dev.txt && pytest`
