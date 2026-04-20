from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

import praw
import requests

from reddit_leads.ai import AIReviewResult, apply_ai_review
from reddit_leads.config import Settings, get_settings, load_rules
from reddit_leads.db import (
    fetch_post,
    record_alert,
    init_db,
    log_event,
    mark_digest_sent,
    mark_instant_alert_sent,
    now_iso,
    recent_digest_candidates,
    upsert_post,
)
from reddit_leads.notifications import notify_all
from reddit_leads.scoring import score_post, truncate

UTC = timezone.utc


@dataclass(frozen=True)
class PublicSubmission:
    id: str
    subreddit: str
    title: str
    selftext: str
    author: str | None
    permalink: str
    url: str
    created_utc: float


def build_reddit_client(settings: Settings | None = None) -> praw.Reddit:
    active_settings = settings or get_settings()
    return praw.Reddit(
        client_id=active_settings.reddit_client_id,
        client_secret=active_settings.reddit_client_secret,
        user_agent=active_settings.reddit_user_agent,
    )


def format_instant_alert(row) -> str:
    lines = [
        "Lead alert",
        "",
        f"r/{row['subreddit']} | score {row['score']}",
        row["title"],
        f"Author: u/{row['author']}",
        f"Link: {row['permalink']}",
    ]
    if row["ai_label"]:
        lines.append(f"AI: {row['ai_label']} ({row['ai_confidence']})")
    if row["ai_reason"]:
        lines.append(f"Why: {truncate(row['ai_reason'], 180)}")
    return "\n".join(lines)


def maybe_send_instant_alert(
    post_id: str,
    settings: Settings | None = None,
    notifier: Callable[[str], None] | None = None,
) -> bool:
    active_settings = settings or get_settings()
    row = fetch_post(post_id, active_settings)
    if not row or row["instant_alert_sent"]:
        return False

    notify = notifier or (lambda text: notify_all(text, active_settings))
    alert_title = f"Lead in r/{row['subreddit']} (score {row['score']})"
    alert_message = truncate(row["title"], 180)
    record_alert(
        alert_key=f"instant:{post_id}",
        post_id=post_id,
        kind="instant_lead",
        title=alert_title,
        message=alert_message,
        subreddit=row["subreddit"],
        permalink=row["permalink"],
        score=row["score"],
        settings=active_settings,
    )
    notify(format_instant_alert(row))
    mark_instant_alert_sent(post_id, active_settings)
    log_event("info", "instant_alert", f"Sent instant alert for {post_id}", active_settings)
    return True


def fetch_public_submissions(
    settings: Settings | None = None,
    rules: dict | None = None,
) -> list[PublicSubmission]:
    active_settings = settings or get_settings()
    active_rules = rules or load_rules()
    seen_ids: set[str] = set()
    submissions: list[PublicSubmission] = []

    headers = {"User-Agent": active_settings.reddit_user_agent}
    for subreddit in active_rules["global"]["target_subreddits"]:
        try:
            response = requests.get(
                f"https://www.reddit.com/r/{subreddit}/new.json",
                params={"limit": 100, "raw_json": 1},
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            children = response.json().get("data", {}).get("children", [])
        except Exception as exc:
            log_event("error", "public_reddit_fetch", f"{subreddit}: {exc}", active_settings)
            continue

        for child in children:
            data = child.get("data", {})
            post_id = data.get("id")
            if not post_id or post_id in seen_ids:
                continue

            seen_ids.add(post_id)
            submissions.append(
                PublicSubmission(
                    id=post_id,
                    subreddit=str(data.get("subreddit", subreddit)).lower(),
                    title=data.get("title", "") or "",
                    selftext=data.get("selftext", "") or "",
                    author=data.get("author"),
                    permalink=data.get("permalink", "") or "",
                    url=data.get("url_overridden_by_dest") or data.get("url") or "",
                    created_utc=float(data.get("created_utc", 0)),
                )
            )

    return submissions


def evaluate_submission(
    submission,
    settings: Settings | None = None,
    rules: dict | None = None,
    notifier: Callable[[str], None] | None = None,
    classifier: Callable[[str, str, str], tuple[str | None, float | None, str | None]] | None = None,
) -> dict:
    active_settings = settings or get_settings()
    active_rules = rules or load_rules()
    subreddit = str(submission.subreddit).lower()
    title = submission.title or ""
    body = submission.selftext or ""
    author = str(submission.author) if submission.author else "[deleted]"
    permalink = f"https://reddit.com{submission.permalink}"
    external_url = submission.url or ""

    score_result = score_post(
        subreddit=subreddit,
        title=title,
        body=body,
        rules=active_rules,
        default_min_score=active_settings.match_min_score,
    )
    ai_review: AIReviewResult = apply_ai_review(
        score_result,
        title,
        body,
        subreddit,
        active_settings,
        classifier=classifier,
    )

    existing = fetch_post(submission.id, active_settings)
    timestamp = now_iso()
    post_record = {
        "post_id": submission.id,
        "subreddit": subreddit,
        "title": title,
        "body": body,
        "author": author,
        "permalink": permalink,
        "url": external_url,
        "created_utc": int(submission.created_utc),
        "matched": ai_review.matched,
        "score": ai_review.score,
        "keyword_score": score_result.keyword_score,
        "match_reasons_json": json.dumps(score_result.reasons),
        "ai_label": ai_review.label,
        "ai_confidence": ai_review.confidence,
        "ai_reason": ai_review.reason,
        "review_status": existing["review_status"] if existing else "new",
        "review_notes": existing["review_notes"] if existing else "",
        "reviewed_at": existing["reviewed_at"] if existing else None,
        "contacted_at": existing["contacted_at"] if existing else None,
        "exported_at": existing["exported_at"] if existing else None,
        "instant_alert_sent": existing["instant_alert_sent"] if existing else 0,
        "digest_sent": existing["digest_sent"] if existing else 0,
        "first_seen_at": existing["first_seen_at"] if existing else timestamp,
        "last_seen_at": timestamp,
    }
    upsert_post(post_record, active_settings)

    alert_sent = False
    if ai_review.matched and ai_review.score >= active_settings.instant_alert_score:
        alert_sent = maybe_send_instant_alert(submission.id, active_settings, notifier=notifier)

    return {
        "post_id": submission.id,
        "matched": ai_review.matched,
        "score": ai_review.score,
        "alert_sent": alert_sent,
    }


def poll_once(
    settings: Settings | None = None,
    rules: dict | None = None,
    reddit_client: praw.Reddit | None = None,
    notifier: Callable[[str], None] | None = None,
    classifier: Callable[[str, str, str], tuple[str | None, float | None, str | None]] | None = None,
) -> int:
    active_settings = settings or get_settings()
    active_rules = rules or load_rules()
    submissions: Iterable

    if reddit_client is not None:
        subreddit_names = "+".join(active_rules["global"]["target_subreddits"])
        submissions = reddit_client.subreddit(subreddit_names).new(limit=100)
    elif active_settings.reddit_client_id and active_settings.reddit_client_secret:
        try:
            client = build_reddit_client(active_settings)
            subreddit_names = "+".join(active_rules["global"]["target_subreddits"])
            submissions = client.subreddit(subreddit_names).new(limit=100)
            submissions = list(submissions)
        except Exception as exc:
            log_event(
                "warning",
                "reddit_auth_fallback",
                f"Falling back to public Reddit feed: {exc}",
                active_settings,
            )
            submissions = fetch_public_submissions(active_settings, active_rules)
    else:
        submissions = fetch_public_submissions(active_settings, active_rules)

    count = 0
    for submission in submissions:
        evaluate_submission(
            submission,
            settings=active_settings,
            rules=active_rules,
            notifier=notifier,
            classifier=classifier,
        )
        count += 1
    return count


def format_digest(rows: Iterable) -> str:
    rows = list(rows)
    lines = [f"Reddit lead digest ({len(rows)} matches)", ""]
    for row in rows:
        lines.append(f"r/{row['subreddit']} | score {row['score']}")
        lines.append(truncate(row["title"], 120))
        lines.append(row["permalink"])
        if row["ai_label"]:
            lines.append(f"AI: {row['ai_label']}")
        lines.append("")
    return "\n".join(lines).strip()


def send_digest(
    settings: Settings | None = None,
    notifier: Callable[[str], None] | None = None,
) -> int:
    active_settings = settings or get_settings()
    rows = recent_digest_candidates(active_settings.digest_interval_minutes, active_settings)
    if not rows:
        log_event("info", "digest", "No digest candidates", active_settings)
        return 0

    selected = rows[:20]
    notify = notifier or (lambda text: notify_all(text, active_settings))
    notify(format_digest(selected))
    mark_digest_sent([row["post_id"] for row in selected], active_settings)
    log_event("info", "digest", f"Sent digest for {len(selected)} posts", active_settings)
    return len(selected)


def run_worker_loop(
    settings: Settings | None = None,
    rules: dict | None = None,
    notifier: Callable[[str], None] | None = None,
    classifier: Callable[[str, str, str], tuple[str | None, float | None, str | None]] | None = None,
) -> None:
    active_settings = settings or get_settings()
    active_rules = rules or load_rules()
    init_db(active_settings)
    log_event("info", "startup", "Worker loop started", active_settings)

    next_digest_at = datetime.now(UTC) + timedelta(minutes=active_settings.digest_interval_minutes)

    while True:
        try:
            poll_once(
                settings=active_settings,
                rules=active_rules,
                notifier=notifier,
                classifier=classifier,
            )
        except Exception as exc:
            log_event("error", "worker_poll", str(exc), active_settings)
            notify_all(f"Reddit monitor error: {exc}", active_settings)

        if datetime.now(UTC) >= next_digest_at:
            try:
                send_digest(active_settings, notifier=notifier)
            except Exception as exc:
                log_event("error", "digest", str(exc), active_settings)
            next_digest_at = datetime.now(UTC) + timedelta(minutes=active_settings.digest_interval_minutes)

        time.sleep(active_settings.poll_seconds)


def main() -> None:
    run_worker_loop()


if __name__ == "__main__":
    main()
