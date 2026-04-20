from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

import requests

from reddit_leads.config import Settings, get_settings
from reddit_leads.db import log_event
from reddit_leads.scoring import ScoreResult


@dataclass(frozen=True)
class AIReviewResult:
    matched: bool
    score: int
    label: str | None
    confidence: float | None
    reason: str | None


def _extract_output_text(payload: dict) -> str:
    choices = payload.get("choices", [])
    if not choices:
        return ""

    message = choices[0].get("message", {})
    content = message.get("content", "")
    return content.strip() if isinstance(content, str) else ""


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("No text returned from AI classification")

    fenced = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = fenced.group(0) if fenced else text
    return json.loads(candidate)


def classify_post(
    title: str,
    body: str,
    subreddit: str,
    settings: Settings | None = None,
    post_func: Callable[..., requests.Response] = requests.post,
) -> tuple[str | None, float | None, str | None]:
    active_settings = settings or get_settings()
    if not active_settings.enable_ai_classification or not active_settings.groq_api_key:
        return None, None, None

    payload = {
        "model": active_settings.groq_model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Classify whether this Reddit post is a real web-development sales lead. "
                    "Return compact JSON with keys: label, confidence, reason. "
                    "label must be one of: hot, warm, weak, reject. "
                    "A hot lead explicitly wants a website, landing page, redesign, web developer, or quote. "
                    "A reject is not an actionable client lead. "
                    "Treat freelancer self-promotion, portfolio posts, service ads, and [FOR HIRE] posts as reject unless the author is clearly buying."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "subreddit": subreddit,
                        "title": title,
                        "body": body,
                    }
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {active_settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = post_func(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        parsed = _extract_json(_extract_output_text(response.json()))
        label = parsed.get("label")
        confidence = parsed.get("confidence")
        reason = parsed.get("reason")
        return label, float(confidence) if confidence is not None else None, reason
    except Exception as exc:
        log_event("error", "ai_classification", f"AI classification failed: {exc}", active_settings)
        return None, None, None


def apply_ai_review(
    score_result: ScoreResult,
    title: str,
    body: str,
    subreddit: str,
    settings: Settings | None = None,
    classifier: Callable[[str, str, str], tuple[str | None, float | None, str | None]] | None = None,
) -> AIReviewResult:
    active_settings = settings or get_settings()
    classifier_func = classifier or (lambda t, b, s: classify_post(t, b, s, active_settings))

    if not active_settings.enable_ai_classification:
        return AIReviewResult(score_result.matched, score_result.score, None, None, None)

    if score_result.keyword_score < active_settings.ai_min_keyword_score:
        return AIReviewResult(score_result.matched, score_result.score, None, None, None)

    label, confidence, reason = classifier_func(title, body, subreddit)
    matched = score_result.matched
    final_score = score_result.score

    if label == "reject":
        matched = False
        final_score -= 3
    elif label == "hot":
        matched = True
        final_score += 3
    elif label == "warm":
        final_score += 1

    return AIReviewResult(matched, final_score, label, confidence, reason)
