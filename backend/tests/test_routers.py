"""HTTP-level tests for the prompts router and the channel-driven estimate guard.

These build a bare FastAPI app with just the router under test and a manually
populated app.state, so the real lifespan (config load, monitor thread) is not
involved.
"""

from __future__ import annotations

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import estimates, prompts, summaries
from yt_summarizer.database import Database


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
