"""ClaudeSummarizer: the estimate must count exactly the request that is billed,
and extraction prompts must return parsed mentions or fail loudly."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yt_summarizer.claude_client import (
    ClaudeSummarizer,
    Extraction,
    ModelSettings,
    SummarizerError,
)
from yt_summarizer.config import ModelPricing
from yt_summarizer.models import ClaudeModel
from yt_summarizer.transcripts import Segment, Transcript

PRICING = ModelPricing(input_per_mtok=1.0, output_per_mtok=5.0)
SETTINGS = ModelSettings(model="m", effort="low", max_output_tokens=4096, pricing=PRICING)
NO_EFFORT = ModelSettings(model="m", effort=None, max_output_tokens=4096, pricing=PRICING)


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
    def __init__(
        self, text: str, stop_reason: str = "end_turn", thinking_tokens: int | None = None
    ) -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.details = (
            None if thinking_tokens is None else SimpleNamespace(thinking_tokens=thinking_tokens)
        )
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
                usage=SimpleNamespace(
                    input_tokens=1234, output_tokens=56, output_tokens_details=self.details
                ),
            )
        )


def _summarizer(
    text: str = "", stop_reason: str = "end_turn", thinking_tokens: int | None = None
) -> ClaudeSummarizer:
    summarizer = ClaudeSummarizer()
    summarizer._client = SimpleNamespace(
        messages=FakeMessages(text, stop_reason, thinking_tokens)
    )
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


def test_plain_prompt_sends_its_settings_and_no_format():
    summarizer = _summarizer("A summary")
    summarizer.summarize(SETTINGS, "system", _transcript())
    kwargs = summarizer._client.messages.stream_kwargs[0]
    assert kwargs["model"] == "m"
    assert kwargs["max_tokens"] == 4096
    assert kwargs["output_config"] == {"effort": "low"}
    assert kwargs["system"] == "system"
    assert kwargs["messages"][0]["content"] == _transcript().text


def test_estimate_and_summarize_send_the_same_request():
    summarizer = _summarizer(_payload())
    extraction = _extraction()
    summarizer.estimate(SETTINGS, "system", _transcript(), 2000, extraction)
    summarizer.summarize(SETTINGS, "system", _transcript(), extraction)

    counted = summarizer._client.messages.count_kwargs[0]
    streamed = dict(summarizer._client.messages.stream_kwargs[0])
    streamed.pop("max_tokens")
    assert counted == streamed


def test_extraction_request_carries_the_schema_and_timestamps():
    summarizer = _summarizer(_payload())
    summarizer.summarize(SETTINGS, "system", _transcript(), _extraction())
    kwargs = summarizer._client.messages.stream_kwargs[0]

    assert kwargs["output_config"]["effort"] == "low"
    schema = kwargs["output_config"]["format"]["schema"]
    stance = schema["properties"]["mentions"]["items"]["properties"]["stance"]
    assert stance["enum"] == ["bullish", "bearish"]
    assert kwargs["messages"][0]["content"].startswith("[00:00] bitcoin is going up")
    assert "[00:45] ethereum is not" in kwargs["messages"][0]["content"]
    assert "Bitcoin" in kwargs["system"]


def test_transcript_without_segments_asks_for_null_timestamps():
    summarizer = _summarizer(_payload(timestamp_seconds=None))
    summarizer.summarize(SETTINGS, "system", Transcript(text="flat text"), _extraction())
    kwargs = summarizer._client.messages.stream_kwargs[0]
    assert kwargs["messages"][0]["content"] == "flat text"
    assert "no timestamps" in kwargs["system"]


def test_extraction_result_is_parsed():
    result = _summarizer(_payload()).summarize(SETTINGS, "system", _transcript(), _extraction())
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
        _summarizer("not json").summarize(SETTINGS, "system", _transcript(), _extraction())


def test_unknown_stance_raises():
    payload = _payload(stance="mooning")
    with pytest.raises(SummarizerError, match="unknown stance"):
        _summarizer(payload).summarize(SETTINGS, "system", _transcript(), _extraction())


def test_truncated_extraction_raises_instead_of_warning():
    summarizer = _summarizer(_payload()[:40], stop_reason="max_tokens")
    with pytest.raises(SummarizerError, match="max output tokens"):
        summarizer.summarize(SETTINGS, "system", _transcript(), _extraction())


def test_plain_prompt_tolerates_max_tokens():
    summarizer = _summarizer("half a summ", stop_reason="max_tokens")
    assert summarizer.summarize(SETTINGS, "system", _transcript()).text == "half a summ"


def test_answer_estimate_and_answer_send_the_same_request():
    summarizer = _summarizer("An answer [1].")
    summarizer.estimate_answer(SETTINGS, "What about Bitcoin?", "[1] source", 1500)
    summarizer.answer(SETTINGS, "What about Bitcoin?", "[1] source")

    counted = summarizer._client.messages.count_kwargs[0]
    streamed = dict(summarizer._client.messages.stream_kwargs[0])
    assert streamed.pop("max_tokens") == 4096
    assert counted == streamed
    assert counted["output_config"] == {"effort": "low"}


def test_cost_uses_the_pricing_of_its_settings():
    summarizer = _summarizer("A summary")
    result = summarizer.summarize(SETTINGS, "system", _transcript())
    assert result.cost_usd == pytest.approx(1234 / 1e6 * 1.0 + 56 / 1e6 * 5.0)


def test_a_model_without_effort_gets_no_output_config():
    summarizer = _summarizer("An answer [1].")
    summarizer.summarize(NO_EFFORT, "system", _transcript())
    summarizer.answer(NO_EFFORT, "What about Bitcoin?", "[1] source")

    summarized, answered = summarizer._client.messages.stream_kwargs
    assert "output_config" not in summarized
    assert "output_config" not in answered


def test_extraction_without_effort_sends_only_the_format():
    summarizer = _summarizer(_payload())
    summarizer.summarize(NO_EFFORT, "system", _transcript(), _extraction())

    output_config = summarizer._client.messages.stream_kwargs[0]["output_config"]
    assert list(output_config) == ["format"]


def _model_info(model_id: str, name: str, *efforts: str):
    supported = {level: SimpleNamespace(supported=level in efforts) for level in
                 ("low", "medium", "high", "xhigh", "max")}
    effort = SimpleNamespace(supported=bool(efforts), **supported)
    return SimpleNamespace(
        id=model_id, display_name=name, capabilities=SimpleNamespace(effort=effort)
    )


def test_listed_models_keep_their_family_and_supported_efforts():
    summarizer = ClaudeSummarizer()
    listed = [
        _model_info("claude-opus-9", "Claude Opus 9", "low", "high", "max"),
        _model_info("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
        _model_info("claude-mythos-5-1", "Claude Mythos 5.1", "low"),
        SimpleNamespace(id="claude-sonnet-7", display_name="Claude Sonnet 7", capabilities=None),
    ]
    summarizer._client = SimpleNamespace(models=SimpleNamespace(list=lambda: listed))

    assert summarizer.list_models() == [
        ClaudeModel("opus", "claude-opus-9", "Claude Opus 9", ("low", "high", "max")),
        ClaudeModel("haiku", "claude-haiku-4-5-20251001", "Claude Haiku 4.5", ()),
        ClaudeModel("sonnet", "claude-sonnet-7", "Claude Sonnet 7", ()),
    ]


def test_summary_reports_thinking_tokens_and_duration():
    result = _summarizer("A summary", thinking_tokens=40).summarize(
        SETTINGS, "system", _transcript()
    )
    assert (result.tokens_output, result.tokens_thinking) == (56, 40)
    assert result.duration_ms is not None and result.duration_ms >= 0


def test_thinking_tokens_are_unknown_when_the_api_omits_the_breakdown():
    result = _summarizer("A summary").summarize(SETTINGS, "system", _transcript())
    assert result.tokens_thinking is None
