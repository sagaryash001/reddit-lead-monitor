from reddit_leads.config import get_settings, load_rules
from reddit_leads.scoring import normalize, score_post


def test_normalize_collapses_whitespace():
    assert normalize(" Need   A Website \n Now ") == "need a website now"


def test_score_post_detects_commercial_buying_intent():
    settings = get_settings()
    rules = load_rules()
    result = score_post(
        subreddit="smallbusiness",
        title="Need a website for my business",
        body="Budget is $1200 and please message me with quotes.",
        rules=rules,
        default_min_score=settings.match_min_score,
    )
    assert result.matched is True
    assert result.score >= 10
    assert "signal:budget" in result.reasons
    assert "signal:contact_intent" in result.reasons
    assert "signal:commercial_need" in result.reasons


def test_score_post_applies_negative_keywords():
    settings = get_settings()
    rules = load_rules()
    result = score_post(
        subreddit="forhire",
        title="Full-time web developer needed",
        body="Salary range posted by the hiring manager.",
        rules=rules,
        default_min_score=settings.match_min_score,
    )
    assert result.matched is False
    assert result.score < 0
    assert any(reason.startswith("negative:full-time") for reason in result.reasons)
