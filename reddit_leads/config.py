from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

REVIEW_STATUSES = {"new", "qualified", "rejected", "contacted"}


@dataclass(frozen=True)
class Settings:
    db_path: str
    lead_rules_path: str
    poll_seconds: int
    digest_interval_minutes: int
    instant_alert_score: int
    match_min_score: int
    dashboard_max_rows: int
    ai_min_keyword_score: int
    groq_api_key: str
    groq_model: str
    enable_ai_classification: bool
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    slack_webhook_url: str
    discord_webhook_url: str
    telegram_bot_token: str
    telegram_chat_id: str


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = _project_root() / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    root = _project_root()
    default_rules = root / "config" / "lead_rules.json"
    return Settings(
        db_path=os.getenv("DB_PATH", str(root / "reddit_leads.db")),
        lead_rules_path=os.getenv("LEAD_RULES_PATH", str(default_rules)),
        poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
        digest_interval_minutes=int(os.getenv("DIGEST_INTERVAL_MINUTES", "60")),
        instant_alert_score=int(os.getenv("INSTANT_ALERT_SCORE", "8")),
        match_min_score=int(os.getenv("MATCH_MIN_SCORE", "4")),
        dashboard_max_rows=int(os.getenv("DASHBOARD_MAX_ROWS", "100")),
        ai_min_keyword_score=int(os.getenv("AI_MIN_KEYWORD_SCORE", "4")),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        enable_ai_classification=os.getenv("ENABLE_AI_CLASSIFICATION", "false").lower() == "true",
        reddit_client_id=os.getenv("REDDIT_CLIENT_ID", ""),
        reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
        reddit_user_agent=os.getenv(
            "REDDIT_USER_AGENT",
            "script:reddit-lead-monitor:v1.0 (by /u/your_username)",
        ),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )


@lru_cache(maxsize=1)
def load_rules() -> dict[str, Any]:
    settings = get_settings()
    with open(settings.lead_rules_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def clear_caches() -> None:
    get_settings.cache_clear()
    load_rules.cache_clear()
