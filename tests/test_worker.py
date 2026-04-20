from types import SimpleNamespace

from reddit_leads.config import get_settings, load_rules
from reddit_leads.db import fetch_alerts, fetch_post, init_db
from reddit_leads.worker import evaluate_submission, poll_once


def _submission(post_id: str):
    return SimpleNamespace(
        id=post_id,
        subreddit="forhire",
        title="Need a website for my business",
        selftext="Budget is $900. DM me.",
        author="prospect",
        permalink="/r/forhire/comments/test/example/",
        url="https://reddit.com/r/forhire/comments/test/example/",
        created_utc=1713600000,
    )


class FakeSubreddit:
    def __init__(self, submissions):
        self._submissions = submissions

    def new(self, limit: int = 100):
        return list(self._submissions)[:limit]


class FakeReddit:
    def __init__(self, submissions):
        self._submissions = submissions

    def subreddit(self, _: str):
        return FakeSubreddit(self._submissions)


def test_evaluate_submission_is_idempotent_for_alerts(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_CLASSIFICATION", "false")
    settings = get_settings()
    rules = load_rules()
    init_db(settings)

    notifications: list[str] = []
    submission = _submission("dup-1")

    evaluate_submission(
        submission,
        settings=settings,
        rules=rules,
        notifier=notifications.append,
    )
    evaluate_submission(
        submission,
        settings=settings,
        rules=rules,
        notifier=notifications.append,
    )

    row = fetch_post("dup-1", settings)
    alerts = fetch_alerts(limit=10, order="desc", settings=settings)
    assert row is not None
    assert row["instant_alert_sent"] == 1
    assert len(notifications) == 1
    assert len(alerts) == 1
    assert alerts[0]["post_id"] == "dup-1"


def test_poll_once_stores_submissions():
    settings = get_settings()
    rules = load_rules()
    init_db(settings)
    reddit_client = FakeReddit([_submission("poll-1"), _submission("poll-2")])

    count = poll_once(settings=settings, rules=rules, reddit_client=reddit_client, notifier=lambda _: None)

    assert count == 2
    assert fetch_post("poll-1", settings) is not None
    assert fetch_post("poll-2", settings) is not None
