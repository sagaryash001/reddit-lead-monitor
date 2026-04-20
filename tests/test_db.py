from datetime import datetime, timedelta, timezone

from reddit_leads.config import get_settings
from reddit_leads.db import (
    fetch_alerts,
    fetch_latest_alert_id,
    fetch_post,
    init_db,
    mark_instant_alert_sent,
    recent_digest_candidates,
    record_alert,
    upsert_post,
)

UTC = timezone.utc


def _post_payload(post_id: str, first_seen_at: str):
    return {
        "post_id": post_id,
        "subreddit": "smallbusiness",
        "title": "Need a website for my bakery",
        "body": "Looking for a web developer",
        "author": "owner1",
        "permalink": "https://reddit.com/test",
        "url": "https://example.com",
        "created_utc": 1,
        "matched": True,
        "score": 8,
        "keyword_score": 8,
        "match_reasons_json": '["strong:need a website"]',
        "ai_label": None,
        "ai_confidence": None,
        "ai_reason": None,
        "review_status": "new",
        "review_notes": "",
        "reviewed_at": None,
        "contacted_at": None,
        "exported_at": None,
        "instant_alert_sent": 0,
        "digest_sent": 0,
        "first_seen_at": first_seen_at,
        "last_seen_at": first_seen_at,
    }


def test_upsert_preserves_first_seen_and_alert_flags():
    settings = get_settings()
    init_db(settings)
    first_seen = datetime.now(UTC).isoformat()
    upsert_post(_post_payload("abc123", first_seen), settings)
    mark_instant_alert_sent("abc123", settings)

    updated = _post_payload("abc123", datetime.now(UTC).isoformat())
    updated["title"] = "Updated title"
    upsert_post(updated, settings)

    row = fetch_post("abc123", settings)
    assert row["title"] == "Updated title"
    assert row["first_seen_at"] == first_seen
    assert row["instant_alert_sent"] == 1


def test_recent_digest_candidates_respects_window():
    settings = get_settings()
    init_db(settings)
    inside_window = datetime.now(UTC).isoformat()
    outside_window = (datetime.now(UTC) - timedelta(minutes=120)).isoformat()
    upsert_post(_post_payload("inside", inside_window), settings)
    upsert_post(_post_payload("outside", outside_window), settings)

    rows = recent_digest_candidates(60, settings)
    assert [row["post_id"] for row in rows] == ["inside"]


def test_record_alert_dedupes_by_alert_key():
    settings = get_settings()
    init_db(settings)

    created_first = record_alert(
        alert_key="instant:lead-1",
        post_id="lead-1",
        kind="instant_lead",
        title="Lead in r/forhire (score 10)",
        message="Need a landing page",
        subreddit="forhire",
        permalink="https://reddit.com/test",
        score=10,
        settings=settings,
    )
    created_second = record_alert(
        alert_key="instant:lead-1",
        post_id="lead-1",
        kind="instant_lead",
        title="Lead in r/forhire (score 10)",
        message="Need a landing page",
        subreddit="forhire",
        permalink="https://reddit.com/test",
        score=10,
        settings=settings,
    )

    alerts = fetch_alerts(limit=10, order="desc", settings=settings)
    assert created_first is True
    assert created_second is False
    assert fetch_latest_alert_id(settings) == 1
    assert len(alerts) == 1
