# Reddit Lead Monitor

Reddit Lead Monitor is a lead-generation system for web development outreach. It watches targeted subreddits, scores posts for buyer intent, stores leads in SQLite, exposes a FastAPI dashboard, and sends notifications to desktop and phone channels.

This project is built for a simple workflow:

- a Python worker runs continuously and finds leads
- a FastAPI app gives you a local dashboard and APIs
- a Chrome extension shows browser notifications from the backend alert feed
- Telegram, Slack, or Discord handle phone notifications

## What It Does

- polls configured subreddits for new posts
- scores posts with keyword, subreddit, and intent signals
- optionally runs Groq-based AI qualification after keyword filtering
- stores all leads and events in SQLite
- sends instant alerts for high-scoring matches
- builds digest notifications for recent matches
- lets you review leads as `new`, `qualified`, `rejected`, or `contacted`
- exports reviewed leads as CSV
- exposes an alert feed that the Chrome extension can poll

## Architecture

The app has three parts:

1. `reddit_leads.worker`
   - background process that fetches Reddit posts, scores them, stores them, and sends alerts
2. `reddit_leads.web`
   - FastAPI app serving the dashboard and APIs
3. `extension/`
   - Chrome extension that polls `/api/alerts` and shows desktop notifications

Important operational detail:

- the Chrome extension is not the scraper
- the Python worker is the always-on monitor
- for true 24/7 monitoring, run the worker on an always-on machine or server

## Features

- SQLite-backed lead storage with dedupe
- subreddit-specific lead rules in `config/lead_rules.json`
- optional Groq AI filtering
- alert feed for browser clients
- FastAPI dashboard and JSON APIs
- CSV export for qualified or contacted leads
- manual review workflow
- webhook-based phone notifications

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Then start both processes:

```bash
python -m reddit_leads.worker
uvicorn reddit_leads.web:app --reload
```

Open:

- dashboard: `http://127.0.0.1:8000`
- health check: `http://127.0.0.1:8000/health`

## Configuration

Environment variables live in `.env`.

### Required for authenticated Reddit API access

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USER_AGENT`

If these are not set, the worker can fall back to Reddit public JSON reads for local testing, but authenticated API access is the intended production path.

### Optional AI qualification with Groq

- `ENABLE_AI_CLASSIFICATION=true`
- `GROQ_API_KEY=...`
- `GROQ_MODEL=llama-3.1-8b-instant`
- `AI_MIN_KEYWORD_SCORE=4`

Simple setup for a personal Groq key:

1. Create a Groq API key in your Groq dashboard.
2. Open your local `.env` file.
3. Add these lines:

```env
ENABLE_AI_CLASSIFICATION=true
GROQ_API_KEY=your_personal_groq_api_key_here
GROQ_MODEL=llama-3.1-8b-instant
AI_MIN_KEYWORD_SCORE=4
```

4. Restart the worker and web app:

```bash
python -m reddit_leads.worker
uvicorn reddit_leads.web:app --reload
```

Notes:

- keep the key only in `.env`
- do not put the key in the Chrome extension
- do not commit the key to GitHub

### Optional phone notifications

Configure at least one:

- `SLACK_WEBHOOK_URL`
- `DISCORD_WEBHOOK_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Rules configuration

Lead rules live in:

- `config/lead_rules.json`

That file controls:

- target subreddits
- strong keywords
- medium keywords
- negative keywords
- subreddit-specific boosts and minimum scores

## Chrome Extension

The extension is in [`extension/`](./extension).

Load it into Chrome:

1. Open `chrome://extensions`
2. Enable Developer mode
3. Click `Load unpacked`
4. Select the `extension/` folder
5. Open the extension options page
6. Set the backend URL, for example `http://127.0.0.1:8000`

What the extension does:

- polls the backend alert feed
- shows desktop notifications on the laptop
- opens the Reddit link or dashboard from notifications

What it does not do:

- scrape Reddit directly
- run 24/7 on its own
- store backend secrets like Groq or Reddit API keys

## API Surface

Main endpoints:

- `GET /health`
- `GET /`
- `GET /api/stats`
- `GET /api/posts`
- `GET /api/events`
- `GET /api/alerts`
- `GET /api/alerts/latest`
- `PATCH /api/posts/{post_id}`
- `GET /api/export.csv?status=qualified`

## Review Workflow

Each lead can be moved through:

- `new`
- `qualified`
- `rejected`
- `contacted`

Use this to separate raw matches from real outreach candidates.

## Testing

Run the test suite with:

```bash
pytest
```

## Repository Layout

```text
reddit_leads/
  ai.py
  config.py
  db.py
  notifications.py
  scoring.py
  web.py
  worker.py
config/
  lead_rules.json
extension/
tests/
```

## Notes

- This tool is meant to find leads, not auto-message Reddit users.
- Do not commit your `.env` file or API keys.
- For production-style 24/7 operation, run the worker and web app under a process manager or on a VPS.
