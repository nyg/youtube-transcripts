"""HTTP-level tests for the prompts router and the channel-driven estimate guard.

These build a bare FastAPI app with just the router under test and a manually
populated app.state, so the real lifespan (config load, monitor thread) is not
involved.
"""

from __future__ import annotations

import types

import pytest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import estimates, mentions, meta, prompts, questions, search, summaries
from yt_summarizer.config import ModelPricing
from yt_summarizer.claude_client import ModelSettings
from yt_summarizer.database import Database
from yt_summarizer.mentions import Mention


PRICING = {"claude-test": ModelPricing(input_per_mtok=4.0, output_per_mtok=20.0)}
SETTINGS = {"model": "claude-test", "effort": "low"}


def _prompts_client(db: Database) -> TestClient:
    app = FastAPI()
    app.state.db = db
    app.state.config = SimpleNamespace(pricing=PRICING)
    app.include_router(prompts.router)
    return TestClient(app)


def test_prompts_crud_api(tmp_path):
    db = Database(tmp_path / "v.db")
    client = _prompts_client(db)

    r = client.post(
        "/api/prompts",
        json={"name": "sum", "text": "Summarize.", "estimated_output_tokens": 1500, **SETTINGS},
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["estimated_output_tokens"] == 1500
    assert (r.json()["model"], r.json()["effort"]) == ("claude-test", "low")
    assert r.json()["max_output_tokens"] == 8192

    assert [p["name"] for p in client.get("/api/prompts").json()] == ["sum"]

    # Duplicate name -> 409.
    duplicate = client.post("/api/prompts", json={"name": "sum", "text": "x", **SETTINGS})
    assert duplicate.status_code == 409

    # Patch text; name is immutable so it isn't accepted for change.
    r = client.patch(f"/api/prompts/{pid}", json={"text": "New."})
    assert r.status_code == 200 and r.json()["text"] == "New."

    assert client.delete(f"/api/prompts/{pid}").status_code == 204
    assert client.get("/api/prompts").json() == []


def test_add_prompt_rejects_blank(tmp_path):
    client = _prompts_client(Database(tmp_path / "v.db"))
    # Empty text fails Pydantic's min_length (422).
    blank_text = client.post("/api/prompts", json={"name": "n", "text": "", **SETTINGS})
    assert blank_text.status_code == 422
    # Whitespace-only name is rejected server-side after trimming.
    blank_name = client.post("/api/prompts", json={"name": "   ", "text": "t", **SETTINGS})
    assert blank_name.status_code == 422


def test_add_prompt_requires_a_model_and_an_effort(tmp_path):
    client = _prompts_client(Database(tmp_path / "v.db"))
    base = {"name": "n", "text": "t"}

    assert client.post("/api/prompts", json={**base, "effort": "low"}).status_code == 422
    assert client.post("/api/prompts", json={**base, "model": "claude-test"}).status_code == 422
    unknown_effort = client.post("/api/prompts", json={**base, **SETTINGS, "effort": "extreme"})
    assert unknown_effort.status_code == 422


def test_prompt_rejects_a_model_without_pricing(tmp_path):
    db = Database(tmp_path / "v.db")
    client = _prompts_client(db)

    created = client.post("/api/prompts", json={"name": "n", "text": "t", **SETTINGS})
    unknown = client.post(
        "/api/prompts", json={"name": "other", "text": "t", **SETTINGS, "model": "claude-nope"}
    )
    patched = client.patch(f"/api/prompts/{created.json()['id']}", json={"model": "claude-nope"})

    assert unknown.status_code == 422 and "pricing" in unknown.json()["detail"]
    assert patched.status_code == 422
    assert db.get_prompt_by_name("n")["model"] == "claude-test"


def test_patch_sets_model_effort_and_cap_on_an_older_prompt(tmp_path):
    db = Database(tmp_path / "v.db")
    legacy = db.add_prompt("legacy", "sys", 2000)
    client = _prompts_client(db)

    listed = client.get("/api/prompts").json()[0]
    r = client.patch(
        f"/api/prompts/{legacy['id']}",
        json={"model": "claude-test", "effort": "xhigh", "max_output_tokens": 64_000},
    )

    assert (listed["model"], listed["effort"]) == (None, None)
    assert r.status_code == 200
    assert (r.json()["model"], r.json()["effort"], r.json()["max_output_tokens"]) == (
        "claude-test",
        "xhigh",
        64_000,
    )


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
    app.state.config = types.SimpleNamespace(transcript_languages=("en",))
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


def test_estimate_422_when_prompt_has_no_model_or_effort(tmp_path):
    db = Database(tmp_path / "v.db")
    db.add_prompt("legacy", "sys", 2000)
    ch = db.add_channel("@chan", "Chan", "legacy")
    client = _estimates_client(db)

    r = client.post("/api/estimates", json={"channel_id": ch["id"], "video_ids": ["v0"]})

    assert r.status_code == 422
    assert "no model or effort" in r.json()["detail"]


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


def test_summaries_expose_run_stats_and_tolerate_their_absence(tmp_path):
    db = Database(tmp_path / "v.db")
    _seed_summary(db, "old")
    db.save_summary(
        video_id="new", title="T", url="u", published_at=None, transcript="x",
        prompt_name="p", model="m", ai_response="r", tokens_input=1000,
        tokens_output=500, cost_usd=0.1, channel_id=None, effort="medium",
        max_output_tokens=8192, estimated_output_tokens=2000, tokens_thinking=300,
        stop_reason="end_turn", duration_ms=1500,
    )
    client = _summaries_client(db)

    listed = {summary["video_id"]: summary for summary in client.get("/api/summaries").json()}

    assert listed["new"]["effort"] == "medium"
    assert (listed["new"]["tokens_thinking"], listed["new"]["max_output_tokens"]) == (300, 8192)
    assert (listed["new"]["estimated_output_tokens"], listed["new"]["duration_ms"]) == (2000, 1500)
    assert listed["old"]["effort"] is None and listed["old"]["tokens_thinking"] is None
    assert client.get("/api/summaries/new").json()["stop_reason"] == "end_turn"


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
            **SETTINGS,
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
        json={"name": "n", "text": "t", **SETTINGS, "stance_labels": ["Buy", "buy"]},
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


def _search_client(db: Database) -> TestClient:
    app = FastAPI()
    app.state.db = db
    app.include_router(search.router)
    return TestClient(app)


def test_search_endpoint(tmp_path):
    db = Database(tmp_path / "v.db")
    db.save_summary(
        video_id="v0", title="Merge explained", url="https://y/v0",
        published_at="2026-09-01T10:00:00+00:00",
        transcript="the ethereum merge changed staking forever",
        prompt_name="p", model="m", ai_response="Ethereum staking recap",
        tokens_input=1, tokens_output=2, cost_usd=0.1, channel_id=4,
    )
    client = _search_client(db)

    hits = client.get("/api/search", params={"q": "staking"}).json()
    assert {hit["kind"] for hit in hits} == {"transcript", "summary"}
    assert hits[0]["title"] == "Merge explained"

    assert client.get("/api/search", params={"q": "   "}).json() == []
    assert client.get("/api/search", params={"q": "staking", "channel_id": 9}).json() == []


# --- ask across videos -------------------------------------------------------


class _FakeAnswerer:
    def __init__(self) -> None:
        self.contexts: list[str] = []
        self.settings: list = []

    def estimate_answer(self, settings, question, context, estimated_output_tokens):
        from yt_summarizer.claude_client import CostEstimate

        self.contexts.append(context)
        self.settings.append(settings)
        return CostEstimate(
            input_tokens=len(context) // 4,
            estimated_output_tokens=estimated_output_tokens,
            cost_usd=0.25,
        )

    def answer(self, settings, question, context):
        from yt_summarizer.claude_client import AnswerResult

        self.settings.append(settings)
        return AnswerResult(
            text="Cardano turned bearish [1].",
            tokens_input=1000,
            tokens_output=200,
            cost_usd=0.3,
            stop_reason="end_turn",
        )


def _questions_client(db: Database, summarizer: _FakeAnswerer) -> TestClient:
    app = FastAPI()
    app.state.db = db
    app.state.summarizer = summarizer
    app.state.config = SimpleNamespace(
        pricing=PRICING,
        ask=SimpleNamespace(
            max_context_tokens=100_000, estimated_output_tokens=1500, max_output_tokens=6000
        ),
    )
    from app.estimates import EstimateStore

    app.state.questions = EstimateStore()
    app.include_router(questions.router)
    return TestClient(app)


def test_question_estimate_then_answer_is_stored(tmp_path):
    db = Database(tmp_path / "v.db")
    _seed_mentions(db, "v0", "2026-09-09T10:00:00+00:00", ("Cardano", "bearish"))
    summarizer = _FakeAnswerer()
    client = _questions_client(db, summarizer)

    estimate = client.post(
        "/api/questions/estimate",
        json={"question": "What about Cardano?", "channel_id": 7, **SETTINGS},
    )
    assert estimate.status_code == 200
    body = estimate.json()
    assert body["mention_count"] == 1 and body["summary_count"] == 1
    assert body["cost_usd"] == 0.25
    assert (body["model"], body["effort"]) == ("claude-test", "low")
    assert "Cardano: bearish" in summarizer.contexts[0]

    answered = client.post("/api/questions", json={"estimate_id": body["estimate_id"]})
    assert answered.status_code == 200
    assert answered.json()["answer"] == "Cardano turned bearish [1]."
    assert answered.json()["model"] == "claude-test"
    assert summarizer.settings == [ModelSettings("claude-test", "low", 6000)] * 2
    assert answered.json()["sources"][0]["kind"] == "mention"

    # The estimate is consumed, so re-approving it is a 410.
    assert client.post(
        "/api/questions", json={"estimate_id": body["estimate_id"]}
    ).status_code == 410

    listed = client.get("/api/questions", params={"channel_id": 7}).json()
    assert [q["question"] for q in listed] == ["What about Cardano?"]
    assert client.delete(f"/api/questions/{listed[0]['id']}").status_code == 204
    assert client.get("/api/questions").json() == []


def test_question_estimate_422_without_sources(tmp_path):
    client = _questions_client(Database(tmp_path / "v.db"), _FakeAnswerer())
    r = client.post("/api/questions/estimate", json={"question": "anything?", **SETTINGS})
    assert r.status_code == 422
    assert "Nothing to answer from" in r.json()["detail"]


def test_question_estimate_requires_a_priced_model_and_an_effort(tmp_path):
    client = _questions_client(Database(tmp_path / "v.db"), _FakeAnswerer())

    no_choice = client.post("/api/questions/estimate", json={"question": "anything?"})
    unknown = client.post(
        "/api/questions/estimate",
        json={"question": "anything?", **SETTINGS, "model": "claude-nope"},
    )

    assert no_choice.status_code == 422
    assert unknown.status_code == 422 and "pricing" in unknown.json()["detail"]


def test_question_cost_counts_toward_daily_spend(tmp_path):
    db = Database(tmp_path / "v.db")
    _seed_mentions(db, "v0", "2026-09-09T10:00:00+00:00", ("Cardano", "bearish"))
    client = _questions_client(db, _FakeAnswerer())

    before = db.spend_since("1970-01-01T00:00:00+00:00")
    estimate = client.post(
        "/api/questions/estimate", json={"question": "Cardano?", **SETTINGS}
    ).json()
    client.post("/api/questions", json={"estimate_id": estimate["estimate_id"]})

    assert db.spend_since("1970-01-01T00:00:00+00:00") == pytest.approx(before + 0.3)


def test_meta_lists_the_priced_models_and_effort_levels(tmp_path):
    app = FastAPI()
    app.state.db = Database(tmp_path / "v.db")
    app.state.monitor = SimpleNamespace(next_run_at=None)
    app.state.config = SimpleNamespace(
        pricing=PRICING,
        max_videos_fetch=25,
        monitor=SimpleNamespace(enabled=False, schedule="0 * * * *", daily_budget_usd=1.0),
    )
    app.include_router(meta.router)

    body = TestClient(app).get("/api/meta").json()

    assert body["models"] == ["claude-test"]
    assert body["efforts"] == ["low", "medium", "high", "xhigh", "max"]
