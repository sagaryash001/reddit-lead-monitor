from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from reddit_leads.config import REVIEW_STATUSES, Settings, get_settings

UTC = timezone.utc


@dataclass(frozen=True)
class PostFilters:
    subreddit: str | None = None
    matched: bool | None = None
    ai_label: str | None = None
    review_status: str | None = None
    limit: int | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_conn(settings: Settings | None = None) -> sqlite3.Connection:
    active_settings = settings or get_settings()
    conn = sqlite3.connect(active_settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(settings: Settings | None = None) -> None:
    conn = get_conn(settings)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY,
            subreddit TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            permalink TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            created_utc INTEGER NOT NULL,
            matched INTEGER NOT NULL DEFAULT 0,
            score INTEGER NOT NULL DEFAULT 0,
            keyword_score INTEGER NOT NULL DEFAULT 0,
            match_reasons_json TEXT NOT NULL DEFAULT '[]',
            ai_label TEXT,
            ai_confidence REAL,
            ai_reason TEXT,
            review_status TEXT NOT NULL DEFAULT 'new',
            review_notes TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            contacted_at TEXT,
            exported_at TEXT,
            instant_alert_sent INTEGER NOT NULL DEFAULT 0,
            digest_sent INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_key TEXT NOT NULL UNIQUE,
            post_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            subreddit TEXT NOT NULL,
            permalink TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def log_event(level: str, kind: str, message: str, settings: Settings | None = None) -> None:
    conn = get_conn(settings)
    conn.execute(
        "INSERT INTO events(level, kind, message, created_at) VALUES (?, ?, ?, ?)",
        (level, kind, message, now_iso()),
    )
    conn.commit()
    conn.close()


def fetch_post(post_id: str, settings: Settings | None = None) -> sqlite3.Row | None:
    conn = get_conn(settings)
    row = conn.execute("SELECT * FROM posts WHERE post_id = ?", (post_id,)).fetchone()
    conn.close()
    return row


def upsert_post(post: dict[str, Any], settings: Settings | None = None) -> None:
    conn = get_conn(settings)
    conn.execute(
        """
        INSERT INTO posts (
            post_id, subreddit, title, body, author, permalink, url, created_utc,
            matched, score, keyword_score, match_reasons_json, ai_label, ai_confidence, ai_reason,
            review_status, review_notes, reviewed_at, contacted_at, exported_at,
            instant_alert_sent, digest_sent, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            subreddit=excluded.subreddit,
            title=excluded.title,
            body=excluded.body,
            author=excluded.author,
            permalink=excluded.permalink,
            url=excluded.url,
            created_utc=excluded.created_utc,
            matched=excluded.matched,
            score=excluded.score,
            keyword_score=excluded.keyword_score,
            match_reasons_json=excluded.match_reasons_json,
            ai_label=COALESCE(excluded.ai_label, posts.ai_label),
            ai_confidence=COALESCE(excluded.ai_confidence, posts.ai_confidence),
            ai_reason=COALESCE(excluded.ai_reason, posts.ai_reason),
            last_seen_at=excluded.last_seen_at
        """,
        (
            post["post_id"],
            post["subreddit"],
            post["title"],
            post.get("body", ""),
            post.get("author", ""),
            post["permalink"],
            post.get("url", ""),
            post["created_utc"],
            int(post["matched"]),
            post["score"],
            post["keyword_score"],
            post.get("match_reasons_json", "[]"),
            post.get("ai_label"),
            post.get("ai_confidence"),
            post.get("ai_reason"),
            post.get("review_status", "new"),
            post.get("review_notes", ""),
            post.get("reviewed_at"),
            post.get("contacted_at"),
            post.get("exported_at"),
            int(post.get("instant_alert_sent", 0)),
            int(post.get("digest_sent", 0)),
            post["first_seen_at"],
            post["last_seen_at"],
        ),
    )
    conn.commit()
    conn.close()


def mark_instant_alert_sent(post_id: str, settings: Settings | None = None) -> None:
    conn = get_conn(settings)
    conn.execute("UPDATE posts SET instant_alert_sent = 1 WHERE post_id = ?", (post_id,))
    conn.commit()
    conn.close()


def mark_digest_sent(post_ids: list[str], settings: Settings | None = None) -> None:
    if not post_ids:
        return
    conn = get_conn(settings)
    conn.executemany("UPDATE posts SET digest_sent = 1 WHERE post_id = ?", [(pid,) for pid in post_ids])
    conn.commit()
    conn.close()


def mark_exported(post_ids: list[str], settings: Settings | None = None) -> None:
    if not post_ids:
        return
    timestamp = now_iso()
    conn = get_conn(settings)
    conn.executemany(
        "UPDATE posts SET exported_at = ? WHERE post_id = ?",
        [(timestamp, pid) for pid in post_ids],
    )
    conn.commit()
    conn.close()


def recent_digest_candidates(minutes: int, settings: Settings | None = None) -> list[sqlite3.Row]:
    cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    conn = get_conn(settings)
    rows = conn.execute(
        """
        SELECT * FROM posts
        WHERE matched = 1 AND digest_sent = 0 AND first_seen_at >= ?
        ORDER BY score DESC, created_utc DESC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()
    return rows


def fetch_posts(filters: PostFilters, settings: Settings | None = None) -> list[sqlite3.Row]:
    active_settings = settings or get_settings()
    clauses: list[str] = []
    params: list[Any] = []

    if filters.subreddit:
        clauses.append("subreddit = ?")
        params.append(filters.subreddit.lower())
    if filters.matched is not None:
        clauses.append("matched = ?")
        params.append(1 if filters.matched else 0)
    if filters.ai_label:
        clauses.append("ai_label = ?")
        params.append(filters.ai_label)
    if filters.review_status:
        clauses.append("review_status = ?")
        params.append(filters.review_status)

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = filters.limit or active_settings.dashboard_max_rows
    params.append(limit)

    conn = get_conn(active_settings)
    rows = conn.execute(
        f"""
        SELECT * FROM posts
        {where_clause}
        ORDER BY first_seen_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()
    return rows


def fetch_recent_events(limit: int = 25, settings: Settings | None = None) -> list[sqlite3.Row]:
    conn = get_conn(settings)
    rows = conn.execute(
        "SELECT * FROM events ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def record_alert(
    alert_key: str,
    post_id: str,
    kind: str,
    title: str,
    message: str,
    subreddit: str,
    permalink: str,
    score: int,
    settings: Settings | None = None,
) -> bool:
    conn = get_conn(settings)
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO alerts (
            alert_key, post_id, kind, title, message, subreddit, permalink, score, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (alert_key, post_id, kind, title, message, subreddit, permalink, score, now_iso()),
    )
    created = cur.rowcount > 0
    conn.commit()
    conn.close()
    return created


def fetch_latest_alert_id(settings: Settings | None = None) -> int:
    conn = get_conn(settings)
    latest = conn.execute("SELECT COALESCE(MAX(id), 0) AS id FROM alerts").fetchone()["id"]
    conn.close()
    return latest


def fetch_alerts(
    after_id: int = 0,
    limit: int = 20,
    order: str = "desc",
    settings: Settings | None = None,
) -> list[sqlite3.Row]:
    if order not in {"asc", "desc"}:
        raise ValueError(f"Unsupported alert order: {order}")

    direction = "ASC" if order == "asc" else "DESC"
    conn = get_conn(settings)
    rows = conn.execute(
        f"""
        SELECT * FROM alerts
        WHERE id > ?
        ORDER BY id {direction}
        LIMIT ?
        """,
        (after_id, limit),
    ).fetchall()
    conn.close()
    return rows


def fetch_stats(settings: Settings | None = None) -> dict[str, int]:
    conn = get_conn(settings)
    stats = {
        "total": conn.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"],
        "matched": conn.execute("SELECT COUNT(*) AS c FROM posts WHERE matched = 1").fetchone()["c"],
        "instant": conn.execute(
            "SELECT COUNT(*) AS c FROM posts WHERE instant_alert_sent = 1"
        ).fetchone()["c"],
        "digests": conn.execute("SELECT COUNT(*) AS c FROM posts WHERE digest_sent = 1").fetchone()["c"],
        "qualified": conn.execute(
            "SELECT COUNT(*) AS c FROM posts WHERE review_status = 'qualified'"
        ).fetchone()["c"],
        "contacted": conn.execute(
            "SELECT COUNT(*) AS c FROM posts WHERE review_status = 'contacted'"
        ).fetchone()["c"],
    }
    conn.close()
    return stats


def update_post_review(
    post_id: str,
    review_status: str | None,
    review_notes: str | None,
    settings: Settings | None = None,
) -> sqlite3.Row | None:
    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise ValueError(f"Unsupported review status: {review_status}")

    existing = fetch_post(post_id, settings)
    if not existing:
        return None

    next_status = review_status or existing["review_status"]
    next_notes = review_notes if review_notes is not None else existing["review_notes"]
    reviewed_at = None
    contacted_at = None

    if next_status in {"qualified", "rejected", "contacted"}:
        reviewed_at = now_iso()
    if next_status == "contacted":
        contacted_at = now_iso()

    conn = get_conn(settings)
    conn.execute(
        """
        UPDATE posts
        SET review_status = ?, review_notes = ?, reviewed_at = ?, contacted_at = ?
        WHERE post_id = ?
        """,
        (next_status, next_notes, reviewed_at, contacted_at, post_id),
    )
    conn.commit()
    conn.close()
    return fetch_post(post_id, settings)


def fetch_export_rows(review_status: str, settings: Settings | None = None) -> list[sqlite3.Row]:
    conn = get_conn(settings)
    rows = conn.execute(
        """
        SELECT * FROM posts
        WHERE review_status = ?
        ORDER BY score DESC, first_seen_at DESC
        """,
        (review_status,),
    ).fetchall()
    conn.close()
    return rows


def serialize_post(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["matched"] = bool(payload["matched"])
    payload["instant_alert_sent"] = bool(payload["instant_alert_sent"])
    payload["digest_sent"] = bool(payload["digest_sent"])
    try:
        payload["match_reasons"] = json.loads(payload.pop("match_reasons_json", "[]"))
    except json.JSONDecodeError:
        payload["match_reasons"] = []
    return payload


def serialize_alert(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)
