from reddit_leads.ai import apply_ai_review
from reddit_leads.config import clear_caches, get_settings
from reddit_leads.scoring import ScoreResult


def test_ai_review_skips_classifier_below_threshold(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_CLASSIFICATION", "true")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("AI_MIN_KEYWORD_SCORE", "5")
    clear_caches()
    settings = get_settings()

    called = {"value": False}

    def fake_classifier(title: str, body: str, subreddit: str):
        called["value"] = True
        return "hot", 0.9, "Would have matched"

    result = apply_ai_review(
        ScoreResult(matched=False, score=3, keyword_score=3, reasons=[]),
        "Need help",
        "",
        "smallbusiness",
        settings=settings,
        classifier=fake_classifier,
    )
    assert called["value"] is False
    assert result.label is None
    assert result.score == 3


def test_ai_reject_can_suppress_keyword_match(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_CLASSIFICATION", "true")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("AI_MIN_KEYWORD_SCORE", "4")
    clear_caches()
    settings = get_settings()

    result = apply_ai_review(
        ScoreResult(matched=True, score=7, keyword_score=7, reasons=[]),
        "Need a website",
        "But actually just asking for a tutorial.",
        "webdev",
        settings=settings,
        classifier=lambda *_: ("reject", 0.91, "Not a real client lead"),
    )
    assert result.matched is False
    assert result.score == 4
    assert result.label == "reject"
