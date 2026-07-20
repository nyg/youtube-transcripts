"""Database helpers added for monitoring: daily spend and per-channel prompt."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from yt_summarizer.database import Database


def _midnight_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def _insert(db: Database, video_id: str, cost: float | None, processed_at: str) -> None:
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "INSERT INTO video_summaries "
            "(video_id, title, url, transcript, prompt_name, model, ai_response, "
            " cost_usd, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (video_id, "t", "u", "x", "p", "m", "r", cost, processed_at),
        )


def test_spend_since_sums_today_and_ignores_earlier(tmp_path):
    db = Database(tmp_path / "v.db")
    now = datetime.now(timezone.utc)
    today = now.isoformat(timespec="seconds")
    yesterday = (now - timedelta(days=1)).isoformat(timespec="seconds")

    _insert(db, "a", 0.10, today)
    _insert(db, "b", 0.20, today)
    _insert(db, "c", 5.00, yesterday)

    assert db.spend_since(_midnight_iso()) == pytest.approx(0.30)


def test_spend_since_ignores_null_costs(tmp_path):
    db = Database(tmp_path / "v.db")
    today = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _insert(db, "a", None, today)
    _insert(db, "b", 0.25, today)
    assert db.spend_since(_midnight_iso()) == pytest.approx(0.25)


def test_spend_since_zero_when_empty(tmp_path):
    db = Database(tmp_path / "v.db")
    assert db.spend_since(_midnight_iso()) == 0.0


def test_add_channel_stores_prompt(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_channel("@chan", "Chan", "alt")
    assert row["prompt_name"] == "alt"


def test_add_channel_defaults_prompt_to_null(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_channel("@chan", "Chan")
    assert row["prompt_name"] is None


def test_set_channel_prompt_updates_and_clears(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_channel("@chan", "Chan")
    updated = db.set_channel_prompt(row["id"], "alt")
    assert updated is not None and updated["prompt_name"] == "alt"
    cleared = db.set_channel_prompt(row["id"], None)
    assert cleared is not None and cleared["prompt_name"] is None


def test_set_channel_prompt_missing_returns_none(tmp_path):
    db = Database(tmp_path / "v.db")
    assert db.set_channel_prompt(999, "alt") is None
