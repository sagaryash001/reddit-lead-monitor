from __future__ import annotations

import csv
import html
import io
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from reddit_leads.config import REVIEW_STATUSES, get_settings
from reddit_leads.db import (
    PostFilters,
    fetch_alerts,
    fetch_latest_alert_id,
    fetch_export_rows,
    fetch_posts,
    fetch_recent_events,
    fetch_stats,
    init_db,
    mark_exported,
    now_iso,
    serialize_alert,
    serialize_post,
    update_post_review,
)
from reddit_leads.scoring import truncate


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Reddit Lead Monitor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


class PostPatchRequest(BaseModel):
    review_status: Literal["new", "qualified", "rejected", "contacted"] | None = None
    review_notes: str | None = Field(default=None, max_length=2000)


def _build_filters(
    subreddit: str | None,
    matched: bool | None,
    ai_label: str | None,
    review_status: str | None,
    limit: int | None = None,
) -> PostFilters:
    normalized_review_status = review_status if review_status in REVIEW_STATUSES else None
    return PostFilters(
        subreddit=subreddit.lower() if subreddit else None,
        matched=matched,
        ai_label=ai_label or None,
        review_status=normalized_review_status,
        limit=limit,
    )


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"ok": True, "time": now_iso()}


@app.get("/api/stats")
def api_stats() -> JSONResponse:
    return JSONResponse(fetch_stats())


@app.get("/api/posts")
def api_posts(
    subreddit: str | None = None,
    matched: bool | None = None,
    ai_label: str | None = None,
    review_status: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
) -> JSONResponse:
    rows = fetch_posts(_build_filters(subreddit, matched, ai_label, review_status, limit))
    return JSONResponse([serialize_post(row) for row in rows])


@app.get("/api/events")
def api_events(limit: int = Query(default=25, ge=1, le=200)) -> JSONResponse:
    return JSONResponse([dict(row) for row in fetch_recent_events(limit=limit)])


@app.get("/api/alerts/latest")
def api_latest_alert() -> JSONResponse:
    return JSONResponse({"latest_id": fetch_latest_alert_id()})


@app.get("/api/alerts")
def api_alerts(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    order: Literal["asc", "desc"] = "desc",
) -> JSONResponse:
    rows = fetch_alerts(after_id=after_id, limit=limit, order=order)
    return JSONResponse([serialize_alert(row) for row in rows])


@app.patch("/api/posts/{post_id}")
def api_patch_post(post_id: str, payload: PostPatchRequest) -> JSONResponse:
    if payload.review_status is None and payload.review_notes is None:
        raise HTTPException(status_code=400, detail="Provide review_status or review_notes")

    row = update_post_review(post_id, payload.review_status, payload.review_notes)
    if not row:
        raise HTTPException(status_code=404, detail="Post not found")
    return JSONResponse(serialize_post(row))


@app.get("/api/export.csv")
def api_export_csv(status: str = Query(default="qualified")) -> PlainTextResponse:
    if status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported review status")

    rows = fetch_export_rows(status)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "subreddit",
            "title",
            "author",
            "permalink",
            "score",
            "ai_label",
            "first_seen_at",
            "review_notes",
        ]
    )

    exported_ids: list[str] = []
    for row in rows:
        writer.writerow(
            [
                row["subreddit"],
                row["title"],
                row["author"],
                row["permalink"],
                row["score"],
                row["ai_label"] or "",
                row["first_seen_at"],
                row["review_notes"],
            ]
        )
        exported_ids.append(row["post_id"])

    mark_exported(exported_ids)
    headers = {"Content-Disposition": f'attachment; filename="reddit-leads-{status}.csv"'}
    return PlainTextResponse(content=output.getvalue(), media_type="text/csv", headers=headers)


def _option_html(value: str, current: str | None, label: str | None = None) -> str:
    selected = " selected" if current == value else ""
    text = label or value
    return f'<option value="{html.escape(value)}"{selected}>{html.escape(text)}</option>'


@app.get("/", response_class=HTMLResponse)
def dashboard(
    subreddit: str | None = None,
    matched: bool | None = None,
    ai_label: str | None = None,
    review_status: str | None = None,
) -> HTMLResponse:
    settings = get_settings()
    filters = _build_filters(
        subreddit=subreddit,
        matched=matched,
        ai_label=ai_label,
        review_status=review_status,
        limit=settings.dashboard_max_rows,
    )
    stats = fetch_stats()
    rows = [serialize_post(row) for row in fetch_posts(filters)]
    events = fetch_recent_events()

    subreddit_values = sorted({row["subreddit"] for row in rows if row["subreddit"]})
    ai_values = sorted({row["ai_label"] for row in rows if row["ai_label"]})

    row_markup: list[str] = []
    for row in rows:
        reason_text = ", ".join(row.get("match_reasons", [])) or "No keyword reasons recorded"
        ai_text = (
            f"{html.escape(str(row['ai_label']))} ({row['ai_confidence']})"
            if row["ai_label"]
            else "Not run"
        )
        note_value = html.escape(row["review_notes"] or "")
        title = html.escape(row["title"])
        author = html.escape(row["author"])
        permalink = html.escape(row["permalink"])
        row_markup.append(
            f"""
            <tr>
                <td>
                    <div class="lead-title"><a href="{permalink}" target="_blank" rel="noreferrer">{title}</a></div>
                    <div class="lead-meta">u/{author} in r/{html.escape(row['subreddit'])}</div>
                    <div class="lead-snippet">{html.escape(truncate(row['body'], 180))}</div>
                </td>
                <td>{row['score']}</td>
                <td>{'Yes' if row['matched'] else 'No'}</td>
                <td>{html.escape(reason_text)}</td>
                <td>{html.escape(ai_text)}</td>
                <td>{html.escape(row['first_seen_at'])}</td>
                <td>
                    <select id="status-{row['post_id']}" class="status-select">
                        {''.join(_option_html(status, row['review_status'], status.title()) for status in sorted(REVIEW_STATUSES))}
                    </select>
                    <textarea id="notes-{row['post_id']}" class="notes-input" placeholder="Review notes">{note_value}</textarea>
                    <button class="save-btn" onclick="saveReview('{row['post_id']}')">Save</button>
                </td>
            </tr>
            """
        )

    event_markup = "".join(
        f"""
        <tr>
            <td>{html.escape(event['created_at'])}</td>
            <td>{html.escape(event['level'])}</td>
            <td>{html.escape(event['kind'])}</td>
            <td>{html.escape(event['message'])}</td>
        </tr>
        """
        for event in events
    )

    matched_value = ""
    if matched is True:
        matched_value = "true"
    elif matched is False:
        matched_value = "false"

    html_content = f"""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Reddit Lead Monitor</title>
        <style>
            :root {{
                --bg: #f6efe6;
                --panel: rgba(255, 250, 244, 0.86);
                --panel-strong: #fffaf4;
                --text: #1c1917;
                --muted: #6b625b;
                --line: rgba(28, 25, 23, 0.14);
                --accent: #b84f2b;
                --accent-soft: #f5d7c8;
                --success: #256f4f;
                --danger: #8b2f2f;
                --shadow: 0 20px 50px rgba(90, 56, 35, 0.14);
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                min-height: 100vh;
                font-family: "Avenir Next", "Segoe UI", sans-serif;
                color: var(--text);
                background:
                    radial-gradient(circle at top left, rgba(184, 79, 43, 0.20), transparent 24rem),
                    radial-gradient(circle at top right, rgba(26, 111, 100, 0.18), transparent 22rem),
                    linear-gradient(180deg, #f7efe3 0%, #f0e4d3 100%);
            }}
            .shell {{
                max-width: 1420px;
                margin: 0 auto;
                padding: 32px 20px 48px;
            }}
            .hero {{
                background: var(--panel);
                backdrop-filter: blur(12px);
                border: 1px solid var(--line);
                border-radius: 28px;
                padding: 28px;
                box-shadow: var(--shadow);
            }}
            h1, h2 {{
                font-family: "Iowan Old Style", "Palatino Linotype", serif;
                margin: 0;
            }}
            h1 {{
                font-size: clamp(2rem, 4vw, 3.4rem);
                letter-spacing: -0.04em;
            }}
            .hero p {{
                color: var(--muted);
                font-size: 1rem;
                max-width: 60rem;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 14px;
                margin: 22px 0 28px;
            }}
            .card {{
                background: var(--panel-strong);
                border: 1px solid var(--line);
                border-radius: 20px;
                padding: 18px;
            }}
            .card .label {{
                color: var(--muted);
                font-size: 0.9rem;
                text-transform: uppercase;
                letter-spacing: 0.06em;
            }}
            .card .value {{
                margin-top: 8px;
                font-size: 2rem;
                font-weight: 700;
            }}
            .filters, .table-wrap, .events {{
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: 24px;
                padding: 20px;
                box-shadow: var(--shadow);
            }}
            .filters {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 12px;
                align-items: end;
            }}
            .filters label {{
                display: block;
                font-size: 0.85rem;
                margin-bottom: 6px;
                color: var(--muted);
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}
            input, select, textarea, button {{
                width: 100%;
                border-radius: 14px;
                border: 1px solid var(--line);
                padding: 11px 12px;
                font: inherit;
                background: rgba(255, 255, 255, 0.82);
                color: var(--text);
            }}
            textarea {{
                min-height: 88px;
                resize: vertical;
            }}
            button {{
                cursor: pointer;
                background: var(--accent);
                color: white;
                border: none;
                font-weight: 600;
            }}
            button.secondary {{
                background: #efe1d3;
                color: var(--text);
                border: 1px solid var(--line);
            }}
            .actions {{
                display: flex;
                gap: 10px;
            }}
            .section-title {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                margin: 26px 0 12px;
            }}
            .table-wrap {{
                overflow: auto;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                min-width: 1000px;
            }}
            th, td {{
                border-bottom: 1px solid var(--line);
                padding: 14px 12px;
                text-align: left;
                vertical-align: top;
            }}
            th {{
                font-size: 0.84rem;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                color: var(--muted);
            }}
            .lead-title a {{
                color: var(--text);
                text-decoration: none;
                font-weight: 700;
            }}
            .lead-title a:hover {{
                color: var(--accent);
            }}
            .lead-meta, .lead-snippet {{
                margin-top: 6px;
                color: var(--muted);
                font-size: 0.92rem;
            }}
            .status-select {{
                margin-bottom: 8px;
            }}
            .notes-input {{
                margin-bottom: 8px;
            }}
            .events table {{
                min-width: 100%;
            }}
            .muted {{
                color: var(--muted);
            }}
            .toolbar {{
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }}
            @media (max-width: 720px) {{
                .shell {{
                    padding: 18px 14px 32px;
                }}
                .hero, .filters, .table-wrap, .events {{
                    border-radius: 20px;
                }}
            }}
        </style>
        <script>
            async function saveReview(postId) {{
                const status = document.getElementById(`status-${{postId}}`).value;
                const notes = document.getElementById(`notes-${{postId}}`).value;
                const response = await fetch(`/api/posts/${{postId}}`, {{
                    method: "PATCH",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ review_status: status, review_notes: notes }})
                }});
                if (!response.ok) {{
                    const payload = await response.json().catch(() => ({{ detail: "Request failed" }}));
                    alert(payload.detail || "Update failed");
                    return;
                }}
                window.location.reload();
            }}
        </script>
    </head>
    <body>
        <div class="shell">
            <section class="hero">
                <h1>Reddit Lead Monitor</h1>
                <p>
                    Watch live Reddit posts for web-development buying intent, review qualified leads,
                    and export outreach-ready prospects without leaving your local workflow.
                </p>
                <div class="cards">
                    <div class="card"><div class="label">Total Posts</div><div class="value">{stats['total']}</div></div>
                    <div class="card"><div class="label">Matched Leads</div><div class="value">{stats['matched']}</div></div>
                    <div class="card"><div class="label">Instant Alerts</div><div class="value">{stats['instant']}</div></div>
                    <div class="card"><div class="label">Digests Sent</div><div class="value">{stats['digests']}</div></div>
                    <div class="card"><div class="label">Qualified</div><div class="value">{stats['qualified']}</div></div>
                    <div class="card"><div class="label">Contacted</div><div class="value">{stats['contacted']}</div></div>
                </div>
            </section>

            <div class="section-title">
                <h2>Lead Filters</h2>
                <div class="toolbar">
                    <a href="/api/export.csv?status=qualified"><button type="button">Export Qualified CSV</button></a>
                    <a href="/"><button type="button" class="secondary">Reset Filters</button></a>
                </div>
            </div>
            <form class="filters" method="get" action="/">
                <div>
                    <label for="subreddit">Subreddit</label>
                    <select id="subreddit" name="subreddit">
                        <option value="">All</option>
                        {''.join(_option_html(value, subreddit) for value in subreddit_values)}
                    </select>
                </div>
                <div>
                    <label for="matched">Matched</label>
                    <select id="matched" name="matched">
                        <option value="">All</option>
                        {''.join([
                            f'<option value="true"{" selected" if matched_value == "true" else ""}>Matched only</option>',
                            f'<option value="false"{" selected" if matched_value == "false" else ""}>Unmatched only</option>'
                        ])}
                    </select>
                </div>
                <div>
                    <label for="ai_label">AI Label</label>
                    <select id="ai_label" name="ai_label">
                        <option value="">All</option>
                        {''.join(_option_html(value, ai_label) for value in ai_values)}
                    </select>
                </div>
                <div>
                    <label for="review_status">Review Status</label>
                    <select id="review_status" name="review_status">
                        <option value="">All</option>
                        {''.join(_option_html(status, review_status, status.title()) for status in sorted(REVIEW_STATUSES))}
                    </select>
                </div>
                <div class="actions">
                    <button type="submit">Apply</button>
                </div>
            </form>

            <div class="section-title">
                <h2>Recent Leads</h2>
                <span class="muted">Showing up to {settings.dashboard_max_rows} rows.</span>
            </div>
            <section class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Lead</th>
                            <th>Score</th>
                            <th>Matched</th>
                            <th>Reasons</th>
                            <th>AI</th>
                            <th>Seen</th>
                            <th>Review</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(row_markup) if row_markup else '<tr><td colspan="7" class="muted">No posts yet. Start the worker to begin collecting leads.</td></tr>'}
                    </tbody>
                </table>
            </section>

            <div class="section-title">
                <h2>Recent Events</h2>
                <span class="muted">Health and delivery log.</span>
            </div>
            <section class="events">
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Level</th>
                            <th>Kind</th>
                            <th>Message</th>
                        </tr>
                    </thead>
                    <tbody>
                        {event_markup or '<tr><td colspan="4" class="muted">No events recorded yet.</td></tr>'}
                    </tbody>
                </table>
            </section>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html_content)
