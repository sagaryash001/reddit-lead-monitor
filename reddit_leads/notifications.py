from __future__ import annotations

from typing import Callable

import requests

from reddit_leads.config import Settings, get_settings
from reddit_leads.db import log_event


def post_to_slack(
    text: str,
    settings: Settings | None = None,
    post_func: Callable[..., requests.Response] = requests.post,
) -> None:
    active_settings = settings or get_settings()
    if not active_settings.slack_webhook_url:
        return
    post_func(active_settings.slack_webhook_url, json={"text": text}, timeout=20)


def post_to_discord(
    text: str,
    settings: Settings | None = None,
    post_func: Callable[..., requests.Response] = requests.post,
) -> None:
    active_settings = settings or get_settings()
    if not active_settings.discord_webhook_url:
        return
    post_func(active_settings.discord_webhook_url, json={"content": text}, timeout=20)


def post_to_telegram(
    text: str,
    settings: Settings | None = None,
    post_func: Callable[..., requests.Response] = requests.post,
) -> None:
    active_settings = settings or get_settings()
    if not active_settings.telegram_bot_token or not active_settings.telegram_chat_id:
        return

    url = f"https://api.telegram.org/bot{active_settings.telegram_bot_token}/sendMessage"
    post_func(
        url,
        json={
            "chat_id": active_settings.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )


def notify_all(
    text: str,
    settings: Settings | None = None,
    post_func: Callable[..., requests.Response] = requests.post,
) -> None:
    active_settings = settings or get_settings()
    errors: list[str] = []
    for fn in (post_to_slack, post_to_discord, post_to_telegram):
        try:
            fn(text, active_settings, post_func=post_func)
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")
    if errors:
        log_event("error", "notification", " | ".join(errors), active_settings)
