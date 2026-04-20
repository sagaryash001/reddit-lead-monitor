from __future__ import annotations

from pathlib import Path

import pytest

from reddit_leads.config import clear_caches


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = tmp_path / "test.db"
    rules_path = Path(__file__).resolve().parent.parent / "config" / "lead_rules.json"

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("LEAD_RULES_PATH", str(rules_path))
    monkeypatch.setenv("ENABLE_AI_CLASSIFICATION", "false")
    monkeypatch.setenv("GROQ_API_KEY", "")
    clear_caches()
    yield
    clear_caches()
