"""Database helpers added for monitoring: daily spend and per-channel prompt."""

from __future__ import annotations

import json
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


def test_add_channel_stores_notify_emails_as_json(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_channel("@chan", "Chan", "p", ["a@example.com", "b@example.com"])
    assert json.loads(row["notify_emails"]) == ["a@example.com", "b@example.com"]


def test_add_channel_defaults_notify_emails_to_empty(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_channel("@chan", "Chan")
    assert json.loads(row["notify_emails"]) == []


def test_update_channel_sets_prompt_and_emails(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_channel("@chan", "Chan")
    updated = db.update_channel(row["id"], prompt_name="alt", notify_emails=["x@example.com"])
    assert updated is not None
    assert updated["prompt_name"] == "alt"
    assert json.loads(updated["notify_emails"]) == ["x@example.com"]


def test_update_channel_only_changes_provided_fields(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_channel("@chan", "Chan", "alt", ["keep@example.com"])
    # Update only the prompt — emails must be untouched.
    updated = db.update_channel(row["id"], prompt_name="other")
    assert updated is not None
    assert updated["prompt_name"] == "other"
    assert json.loads(updated["notify_emails"]) == ["keep@example.com"]
    # Clear the recipients with an explicit empty list.
    cleared = db.update_channel(row["id"], notify_emails=[])
    assert cleared is not None and json.loads(cleared["notify_emails"]) == []
    assert cleared["prompt_name"] == "other"


def test_update_channel_missing_returns_none(tmp_path):
    db = Database(tmp_path / "v.db")
    assert db.update_channel(999, prompt_name="alt") is None


def test_prompt_crud_roundtrip(tmp_path):
    db = Database(tmp_path / "v.db")
    row = db.add_prompt("summary", "Summarize this.", 1500)
    assert row["name"] == "summary"
    assert row["text"] == "Summarize this."
    assert row["estimated_output_tokens"] == 1500

    fetched = db.get_prompt_by_name("summary")
    assert fetched is not None and fetched["id"] == row["id"]
    assert [p["name"] for p in db.list_prompts()] == ["summary"]

    updated = db.update_prompt(row["id"], text="New text.", estimated_output_tokens=3000)
    assert updated is not None
    assert updated["text"] == "New text."
    assert updated["estimated_output_tokens"] == 3000

    assert db.delete_prompt(row["id"]) is True
    assert db.get_prompt(row["id"]) is None


def test_add_prompt_duplicate_name_raises(tmp_path):
    db = Database(tmp_path / "v.db")
    db.add_prompt("dup", "a", 2000)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_prompt("dup", "b", 2000)


def test_channels_using_prompt_reports_references(tmp_path):
    db = Database(tmp_path / "v.db")
    db.add_prompt("shared", "sys", 2000)
    db.add_channel("@a", "A", "shared")
    db.add_channel("@b", "B", "shared")
    db.add_channel("@c", "C", "other")
    users = db.channels_using_prompt("shared")
    assert {u["label"] for u in users} == {"A", "B"}
    assert db.channels_using_prompt("nobody") == []
