"""Database helpers added for monitoring: daily spend and per-channel prompt."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from yt_summarizer.database import Database
from yt_summarizer.mentions import Mention
from yt_summarizer.transcripts import Segment, segments_from_json, segments_to_json


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


def test_delete_summary_removes_row_and_unmarks_video(tmp_path):
    db = Database(tmp_path / "v.db")
    _insert(db, "v0", 0.10, _midnight_iso())
    _insert(db, "v1", 0.20, _midnight_iso())

    assert db.delete_summary("v0") is True

    assert db.get_summary("v0") is None
    # The video is processable again; the other summary is untouched.
    assert db.processed_ids() == {"v1"}


def test_delete_summary_unknown_video_returns_false(tmp_path):
    db = Database(tmp_path / "v.db")
    assert db.delete_summary("nope") is False


# --- mentions ---------------------------------------------------------------


def _mention(entity: str, stance: str, at: int | None = 12) -> Mention:
    return Mention(
        entity=entity,
        stance=stance,
        confidence="high",
        rationale="because",
        quote="a quote",
        timestamp_seconds=at,
    )


def _save(db: Database, video_id: str, published_at: str, mentions: list[Mention]) -> None:
    db.save_summary(
        video_id=video_id,
        title=f"Video {video_id}",
        url=f"https://www.youtube.com/watch?v={video_id}",
        published_at=published_at,
        transcript="a transcript",
        prompt_name="crypto",
        model="m",
        ai_response="summary",
        tokens_input=10,
        tokens_output=5,
        cost_usd=0.01,
        channel_id=1,
        transcript_segments=None,
        mentions=mentions,
    )


def test_reprocessing_replaces_mentions(tmp_path):
    db = Database(tmp_path / "v.db")
    _save(db, "v0", "2026-09-01T10:00:00+00:00", [_mention("BTC", "bullish")])
    _save(db, "v0", "2026-09-01T10:00:00+00:00", [_mention("ETH", "bearish")])

    rows = db.list_mentions()
    assert [(row["entity"], row["stance"]) for row in rows] == [("ETH", "bearish")]
    assert rows[0]["title"] == "Video v0"


def test_entity_overview_reports_latest_and_previous_stance(tmp_path):
    db = Database(tmp_path / "v.db")
    _save(db, "v0", "2026-09-01T10:00:00+00:00", [_mention("ADA", "bullish")])
    _save(db, "v1", "2026-09-05T10:00:00+00:00", [_mention("ADA", "bullish")])
    _save(db, "v2", "2026-09-10T10:00:00+00:00", [_mention("ada", "bearish")])

    overview = db.entity_overview()
    assert len(overview) == 1
    entry = overview[0]
    assert entry["entity"] == "ada"
    assert entry["latest_stance"] == "bearish"
    assert entry["previous_stance"] == "bullish"
    assert entry["previous_at"] == "2026-09-05T10:00:00+00:00"
    assert entry["mention_count"] == 3
    assert entry["video_count"] == 3


def test_entity_overview_since_filters_by_publish_date(tmp_path):
    db = Database(tmp_path / "v.db")
    _save(db, "v0", "2026-08-01T10:00:00+00:00", [_mention("SOL", "bullish")])
    _save(db, "v1", "2026-09-10T10:00:00+00:00", [_mention("BTC", "bearish")])

    entities = {e["entity"] for e in db.entity_overview(since="2026-09-01T00:00:00+00:00")}
    assert entities == {"BTC"}


def test_deleting_a_summary_deletes_its_mentions(tmp_path):
    db = Database(tmp_path / "v.db")
    _save(db, "v0", "2026-09-01T10:00:00+00:00", [_mention("BTC", "bullish")])
    _save(db, "v1", "2026-09-02T10:00:00+00:00", [_mention("BTC", "bearish")])

    assert db.delete_summary("v0") is True
    assert [row["video_id"] for row in db.list_mentions()] == ["v1"]


def test_known_entities_are_ordered_by_use(tmp_path):
    db = Database(tmp_path / "v.db")
    _save(db, "v0", "2026-09-01T10:00:00+00:00", [_mention("BTC", "bullish")])
    _save(db, "v1", "2026-09-02T10:00:00+00:00", [_mention("BTC", "bullish"), _mention("XRP", "bearish")])

    assert db.known_entities("crypto") == ["BTC", "XRP"]
    assert db.known_entities("other") == []


def test_transcript_segments_round_trip(tmp_path):
    db = Database(tmp_path / "v.db")
    segments = [Segment(start_ms=0, text="hello"), Segment(start_ms=1500, text="world")]
    db.save_summary(
        video_id="v0",
        title="t",
        url="u",
        published_at=None,
        transcript="hello world",
        prompt_name="p",
        model="m",
        ai_response="r",
        tokens_input=1,
        tokens_output=1,
        cost_usd=0.0,
        transcript_segments=segments_to_json(segments),
    )
    row = db.get_summary("v0")
    assert segments_from_json(row["transcript_segments"]) == segments
