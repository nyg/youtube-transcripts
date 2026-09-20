"""ClaudeSummarizer: the estimate must count exactly the request that is billed,
and extraction prompts must return parsed mentions or fail loudly."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yt_summarizer.claude_client import ClaudeSummarizer, Extraction, SummarizerError
from yt_summarizer.config import ModelPricing
from yt_summarizer.transcripts import Segment, Transcript

PRICING = {"m": ModelPricing(input_per_mtok=1.0, output_per_mtok=5.0)}


class _Stream:
    def __init__(self, response) -> None:
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def get_final_message(self):
        return self._response


class FakeMessages:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.count_kwargs: list[dict] = []
        self.stream_kwargs: list[dict] = []

    def count_tokens(self, **kwargs):
        self.count_kwargs.append(kwargs)
        return SimpleNamespace(input_tokens=1234)

    def stream(self, **kwargs):
        self.stream_kwargs.append(kwargs)
        return _Stream(
            SimpleNamespace(
                stop_reason=self.stop_reason,
                content=[SimpleNamespace(type="text", text=self.text)],
                usage=SimpleNamespace(input_tokens=1234, output_tokens=56),
            )
        )


def _summarizer(text: str = "", stop_reason: str = "end_turn") -> ClaudeSummarizer:
    summarizer = ClaudeSummarizer(model="m", max_output_tokens=8192, pricing=PRICING)
    summarizer._client = SimpleNamespace(messages=FakeMessages(text, stop_reason))
    return summarizer


def _transcript() -> Transcript:
    return Transcript(
        text="bitcoin is going up ethereum is not",
        segments=[
            Segment(start_ms=0, text="bitcoin is going up"),
            Segment(start_ms=45_000, text="ethereum is not"),
        ],
    )


def _extraction() -> Extraction:
    return Extraction(
        entity_kind="coin",
        stance_labels=["bullish", "bearish"],
        known_entities=["Bitcoin"],
    )


def _payload(**overrides) -> str:
    mention = {
        "entity": "Bitcoin",
        "stance": "bullish",
        "confidence": "high",
        "rationale": "He expects a new high.",
        "quote": "bitcoin is going up",
        "timestamp_seconds": 45,
    }
    mention.update(overrides)
    return json.dumps({"summary": "**Summary**", "mentions": [mention]})


def test_plain_prompt_sends_no_output_config():
    summarizer = _summarizer("A summary")
    summarizer.summarize("system", _transcript())
    kwargs = summarizer._client.messages.stream_kwargs[0]
    assert "output_config" not in kwargs
    assert kwargs["system"] == "system"
    assert kwargs["messages"][0]["content"] == _transcript().text


def test_estimate_and_summarize_send_the_same_request():
    summarizer = _summarizer(_payload())
    extraction = _extraction()
    summarizer.estimate("system", _transcript(), 2000, extraction)
    summarizer.summarize("system", _transcript(), extraction)

    counted = summarizer._client.messages.count_kwargs[0]
    streamed = dict(summarizer._client.messages.stream_kwargs[0])
    streamed.pop("max_tokens")
    assert counted == streamed


def test_extraction_request_carries_the_schema_and_timestamps():
    summarizer = _summarizer(_payload())
    summarizer.summarize("system", _transcript(), _extraction())
    kwargs = summarizer._client.messages.stream_kwargs[0]

    schema = kwargs["output_config"]["format"]["schema"]
    stance = schema["properties"]["mentions"]["items"]["properties"]["stance"]
    assert stance["enum"] == ["bullish", "bearish"]
    assert kwargs["messages"][0]["content"].startswith("[00:00] bitcoin is going up")
    assert "[00:45] ethereum is not" in kwargs["messages"][0]["content"]
    assert "Bitcoin" in kwargs["system"]


def test_transcript_without_segments_asks_for_null_timestamps():
    summarizer = _summarizer(_payload(timestamp_seconds=None))
    summarizer.summarize("system", Transcript(text="flat text"), _extraction())
    kwargs = summarizer._client.messages.stream_kwargs[0]
    assert kwargs["messages"][0]["content"] == "flat text"
    assert "no timestamps" in kwargs["system"]


def test_extraction_result_is_parsed():
    result = _summarizer(_payload()).summarize("system", _transcript(), _extraction())
    assert result.text == "**Summary**"
    assert len(result.mentions) == 1
    mention = result.mentions[0]
    assert (mention.entity, mention.stance, mention.timestamp_seconds) == (
        "Bitcoin",
        "bullish",
        45,
    )


def test_invalid_json_raises():
    with pytest.raises(SummarizerError, match="invalid JSON"):
        _summarizer("not json").summarize("system", _transcript(), _extraction())


def test_unknown_stance_raises():
    payload = _payload(stance="mooning")
    with pytest.raises(SummarizerError, match="unknown stance"):
        _summarizer(payload).summarize("system", _transcript(), _extraction())


def test_truncated_extraction_raises_instead_of_warning():
    summarizer = _summarizer(_payload()[:40], stop_reason="max_tokens")
    with pytest.raises(SummarizerError, match="max_output_tokens"):
        summarizer.summarize("system", _transcript(), _extraction())


def test_plain_prompt_tolerates_max_tokens():
    summarizer = _summarizer("half a summ", stop_reason="max_tokens")
    assert summarizer.summarize("system", _transcript()).text == "half a summ"
