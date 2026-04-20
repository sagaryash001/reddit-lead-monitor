from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScoreResult:
    matched: bool
    score: int
    keyword_score: int
    reasons: list[str]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def truncate(text: str, limit: int = 300) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def score_post(
    subreddit: str,
    title: str,
    body: str,
    rules: dict[str, Any],
    default_min_score: int,
) -> ScoreResult:
    text = normalize(f"{title} {body}")
    subreddit_key = subreddit.lower()
    subreddit_rules = rules.get("subreddit_rules", {}).get(subreddit_key, {})
    global_rules = rules.get("global", {})

    strong = global_rules.get("strong_keywords", [])
    medium = global_rules.get("medium_keywords", [])
    negatives = list(global_rules.get("negative_keywords", [])) + list(
        subreddit_rules.get("negative_keywords", [])
    )
    boosts = list(subreddit_rules.get("boost_keywords", []))

    score = 0
    reasons: list[str] = []

    for phrase in strong:
        if phrase in text:
            score += 5
            reasons.append(f"strong:{phrase}")

    for phrase in medium:
        if phrase in text:
            score += 1
            reasons.append(f"medium:{phrase}")

    for phrase in boosts:
        if phrase in text:
            score += 2
            reasons.append(f"boost:{phrase}")

    for phrase in negatives:
        if phrase in text:
            score -= 5
            reasons.append(f"negative:{phrase}")

    if "$" in text or "budget" in text:
        score += 2
        reasons.append("signal:budget")

    if "dm me" in text or "message me" in text or "looking for quotes" in text:
        score += 2
        reasons.append("signal:contact_intent")

    if "website" in text and ("business" in text or "client" in text or "company" in text):
        score += 2
        reasons.append("signal:commercial_need")

    min_score = int(subreddit_rules.get("min_score", default_min_score))
    return ScoreResult(
        matched=score >= min_score,
        score=score,
        keyword_score=score,
        reasons=reasons,
    )
