from fastapi.testclient import TestClient

from reddit_leads.db import init_db, record_alert, upsert_post
from reddit_leads.web import app


def _seed_post(post_id: str, review_status: str = "qualified", review_notes: str = "Call tomorrow"):
    timestamp = "2026-04-20T10:00:00+00:00"
    return {
        "post_id": post_id,
        "subreddit": "forhire",
        "title": "Need a landing page for my agency",
        "body": "Budget is set. DM me.",
        "author": "leadowner",
        "permalink": "https://reddit.com/test",
        "url": "https://example.com",
        "created_utc": 10,
        "matched": True,
        "score": 11,
        "keyword_score": 11,
        "match_reasons_json": '["strong:need a landing page"]',
        "ai_label": "warm",
        "ai_confidence": 0.82,
        "ai_reason": "Explicit hiring intent",
        "review_status": review_status,
        "review_notes": review_notes,
        "reviewed_at": timestamp,
        "contacted_at": None,
        "exported_at": None,
        "instant_alert_sent": 1,
        "digest_sent": 0,
        "first_seen_at": timestamp,
        "last_seen_at": timestamp,
    }


def test_api_posts_patch_and_export():
    init_db()
    upsert_post(_seed_post("lead-1"))
    record_alert(
        alert_key="instant:lead-1",
        post_id="lead-1",
        kind="instant_lead",
        title="Lead in r/forhire (score 11)",
        message="Need a landing page for my agency",
        subreddit="forhire",
        permalink="https://reddit.com/test",
        score=11,
    )
    client = TestClient(app)

    posts_response = client.get("/api/posts")
    assert posts_response.status_code == 200
    assert posts_response.json()[0]["post_id"] == "lead-1"
    assert posts_response.json()[0]["match_reasons"] == ["strong:need a landing page"]

    patch_response = client.patch(
        "/api/posts/lead-1",
        json={"review_status": "contacted", "review_notes": "Sent intro message"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["review_status"] == "contacted"
    assert patch_response.json()["review_notes"] == "Sent intro message"
    assert patch_response.json()["contacted_at"] is not None

    export_response = client.get("/api/export.csv?status=contacted")
    assert export_response.status_code == 200
    assert "leadowner" in export_response.text
    assert "Sent intro message" in export_response.text

    latest_alert_response = client.get("/api/alerts/latest")
    assert latest_alert_response.status_code == 200
    assert latest_alert_response.json()["latest_id"] == 1

    alerts_response = client.get("/api/alerts?limit=5&order=desc")
    assert alerts_response.status_code == 200
    assert alerts_response.json()[0]["post_id"] == "lead-1"
