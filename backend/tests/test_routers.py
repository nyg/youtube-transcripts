"""HTTP-level tests for the prompts router and the channel-driven estimate guard.

These build a bare FastAPI app with just the router under test and a manually
populated app.state, so the real lifespan (config load, monitor thread) is not
involved.
"""

from __future__ import annotations

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import estimates, mentions, prompts, summaries
from yt_summarizer.database import Database
from yt_summarizer.mentions import Mention


def _prompts_client(db: Database) -> TestClient:
    app = FastAPI()
    app.state.db = db
    app.include_router(prompts.router)
    return TestClient(app)


def test_prompts_crud_api(tmp_path):
    db = Database(tmp_path / "v.db")
    client = _prompts_client(db)

    r = client.post(
        "/api/prompts",
        json={"name": "sum", "text": "Summarize.", "estimated_output_tokens": 1500},
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["estimated_output_tokens"] == 1500

    assert [p["name"] for p in client.get("/api/prompts").json()] == ["sum"]

    # Duplicate name -> 409.
    assert client.post("/api/prompts", json={"name": "sum", "text": "x"}).status_code == 409

    # Patch text; name is immutable so it isn't accepted for change.
    r = client.patch(f"/api/prompts/{pid}", json={"text": "New."})
    assert r.status_code == 200 and r.json()["text"] == "New."

    assert client.delete(f"/api/prompts/{pid}").status_code == 204
    assert client.get("/api/prompts").json() == []


def test_add_prompt_rejects_blank(tmp_path):
    client = _prompts_client(Database(tmp_path / "v.db"))
    # Empty text fails Pydantic's min_length (422).
    assert client.post("/api/prompts", json={"name": "n", "text": ""}).status_code == 422
    # Whitespace-only name is rejected server-side after trimming.
    assert client.post("/api/prompts", json={"name": "   ", "text": "t"}).status_code == 422


def test_delete_prompt_blocked_when_in_use(tmp_path):
    db = Database(tmp_path / "v.db")
    p = db.add_prompt("used", "sys", 2000)
    db.add_channel("@a", "A", "used")
    client = _prompts_client(db)

    r = client.delete(f"/api/prompts/{p['id']}")
    assert r.status_code == 409
    assert "in use" in r.json()["detail"].lower()
    assert db.get_prompt(p["id"]) is not None  # not deleted


def _estimates_client(db: Database) -> TestClient:
    app = FastAPI()
    app.state.db = db
    # The no-prompt / missing-channel guards return before touching these.
    app.state.config = types.SimpleNamespace(transcript_languages=("en",), model="m")
    app.state.summarizer = None
    app.state.estimates = None
    app.include_router(estimates.router)
    return TestClient(app)


def test_estimate_404_when_channel_missing(tmp_path):
    client = _estimates_client(Database(tmp_path / "v.db"))
    r = client.post("/api/estimates", json={"channel_id": 999, "video_ids": ["v0"]})
    assert r.status_code == 404


def test_estimate_422_when_channel_has_no_prompt(tmp_path):
    db = Database(tmp_path / "v.db")
    ch = db.add_channel("@chan", "Chan")  # no prompt assigned
    client = _estimates_client(db)
    r = client.post("/api/estimates", json={"channel_id": ch["id"], "video_ids": ["v0"]})
    assert r.status_code == 422
    assert "prompt" in r.json()["detail"].lower()


def _summaries_client(db: Database) -> TestClient:
    app = FastAPI()
    app.state.db = db
    app.include_router(summaries.router)
    return TestClient(app)


def _seed_summary(db: Database, video_id: str) -> None:
    db.save_summary(
        video_id=video_id, title="T", url="u", published_at=None, transcript="x",
        prompt_name="p", model="m", ai_response="r", tokens_input=1,
        tokens_output=2, cost_usd=0.1, channel_id=None,
    )


def test_delete_summary_removes_it(tmp_path):
    db = Database(tmp_path / "v.db")
    _seed_summary(db, "v0")
    client = _summaries_client(db)

    assert client.delete("/api/summaries/v0").status_code == 204

    assert db.get_summary("v0") is None
    assert client.get("/api/summaries").json() == []


def test_delete_summary_404_when_missing(tmp_path):
    client = _summaries_client(Database(tmp_path / "v.db"))
    assert client.delete("/api/summaries/nope").status_code == 404


# --- prompt extraction fields + mentions router ------------------------------


def _mentions_client(db: Database) -> TestClient:
    app = FastAPI()
    app.state.db = db
    app.include_router(mentions.router)
    return TestClient(app)


def _seed_mentions(db: Database, video_id: str, published_at: str, *pairs) -> None:
    db.save_summary(
        video_id=video_id, title=f"Video {video_id}", url=f"https://y/{video_id}",
        published_at=published_at, transcript="x", prompt_name="crypto", model="m",
        ai_response="r", tokens_input=1, tokens_output=2, cost_usd=0.1, channel_id=7,
        mentions=[
            Mention(entity=entity, stance=stance, confidence="high",
                    rationale="why", quote="q", timestamp_seconds=30)
            for entity, stance in pairs
        ],
    )


def test_prompt_extraction_fields_round_trip(tmp_path):
    db = Database(tmp_path / "v.db")
    client = _prompts_client(db)

    r = client.post(
        "/api/prompts",
        json={
            "name": "crypto",
            "text": "Summarize.",
            "entity_kind": "coin",
            "stance_labels": [" bullish ", "bearish"],
        },
    )
    assert r.status_code == 201
    assert r.json()["stance_labels"] == ["bullish", "bearish"]
    assert r.json()["entity_kind"] == "coin"

    pid = r.json()["id"]
    r = client.patch(f"/api/prompts/{pid}", json={"stance_labels": []})
    assert r.status_code == 200 and r.json()["stance_labels"] == []


def test_prompt_rejects_duplicate_stance_labels(tmp_path):
    client = _prompts_client(Database(tmp_path / "v.db"))
    r = client.post(
        "/api/prompts",
        json={"name": "n", "text": "t", "stance_labels": ["Buy", "buy"]},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Stance labels must be unique"


def test_entities_and_mentions_endpoints(tmp_path):
    db = Database(tmp_path / "v.db")
    _seed_mentions(db, "v0", "2026-09-01T10:00:00+00:00", ("BTC", "bullish"))
    _seed_mentions(db, "v1", "2026-09-09T10:00:00+00:00", ("BTC", "bearish"), ("SOL", "bullish"))
    client = _mentions_client(db)

    entities = client.get("/api/entities", params={"channel_id": 7}).json()
    btc = next(e for e in entities if e["entity"] == "BTC")
    assert btc["latest_stance"] == "bearish"
    assert btc["previous_stance"] == "bullish"
    assert btc["video_count"] == 2

    timeline = client.get("/api/mentions", params={"entity": "btc"}).json()
    assert [m["video_id"] for m in timeline] == ["v1", "v0"]
    assert timeline[0]["title"] == "Video v1"
    assert timeline[0]["timestamp_seconds"] == 30

    recent = client.get("/api/entities", params={"since": "2026-09-05T00:00:00+00:00"}).json()
    assert {e["entity"] for e in recent} == {"BTC", "SOL"}


def test_summaries_carry_their_mentions(tmp_path):
    db = Database(tmp_path / "v.db")
    _seed_mentions(db, "v0", "2026-09-01T10:00:00+00:00", ("BTC", "bullish"))
    client = _summaries_client(db)

    listed = client.get("/api/summaries").json()
    assert [m["entity"] for m in listed[0]["mentions"]] == ["BTC"]

    detail = client.get("/api/summaries/v0").json()
    assert detail["mentions"][0]["stance"] == "bullish"
