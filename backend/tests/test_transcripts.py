"""Unit tests for caption track selection, json3 parsing, and 429 backoff."""

from __future__ import annotations

import json
from typing import Any

import pytest
from yt_dlp.networking.exceptions import RequestError

from yt_summarizer import transcripts, youtube_client
from yt_summarizer.transcripts import (
    TranscriptError,
    _parse_json3,
    fetch_transcript,
    select_caption_track,
)
from yt_summarizer.youtube_client import YouTubeRateLimitError


def _formats(name: str, *exts: str) -> list[dict[str, str]]:
    return [{"ext": ext, "url": f"https://captions.example/{name}.{ext}"} for ext in exts]


def _url(name: str, ext: str = "json3") -> str:
    return f"https://captions.example/{name}.{ext}"


# --- select_caption_track ---------------------------------------------------


def test_manual_beats_auto_for_same_language():
    info = {
        "subtitles": {"en": _formats("manual-en", "json3", "vtt")},
        "automatic_captions": {"en": _formats("auto-en", "json3")},
    }
    assert select_caption_track(info, ["en"]) == _url("manual-en")


def test_regional_variant_matches_preferred_language():
    info = {
        "subtitles": {"en-GB": _formats("manual-en-gb", "json3")},
        "automatic_captions": {},
    }
    assert select_caption_track(info, ["en"]) == _url("manual-en-gb")


def test_manual_variant_beats_auto_exact():
    info = {
        "subtitles": {"en-GB": _formats("manual-en-gb", "json3")},
        "automatic_captions": {"en": _formats("auto-en", "json3")},
    }
    assert select_caption_track(info, ["en"]) == _url("manual-en-gb")


def test_language_order_wins_over_track_kind():
    info = {
        "subtitles": {"de": _formats("manual-de", "json3")},
        "automatic_captions": {"en": _formats("auto-en", "json3")},
    }
    assert select_caption_track(info, ["en", "de"]) == _url("auto-en")


def test_orig_track_is_last_resort():
    info = {
        "subtitles": {},
        "automatic_captions": {
            "de": _formats("auto-de", "json3"),
            "de-orig": _formats("auto-de-orig", "json3"),
        },
    }
    assert select_caption_track(info, ["en"]) == _url("auto-de-orig")


def test_track_without_json3_is_skipped():
    info = {
        "subtitles": {"en": _formats("manual-en", "vtt")},
        "automatic_captions": {"en": _formats("auto-en", "json3", "vtt")},
    }
    assert select_caption_track(info, ["en"]) == _url("auto-en")


def test_no_captions_returns_none():
    assert select_caption_track({}, ["en"]) is None
    assert select_caption_track({"subtitles": {}, "automatic_captions": {}}, ["en"]) is None


# --- _parse_json3 -----------------------------------------------------------


def _json3(*texts: str) -> str:
    return json.dumps({"events": [{"segs": [{"utf8": t} for t in texts]}]})


def test_parse_json3_joins_segments_with_single_spaces():
    assert _parse_json3(_json3("Hello\nworld", "  again  ")).text == "Hello world again"


def test_parse_json3_empty_input():
    for raw in ("", json.dumps({"events": []}), json.dumps({})):
        parsed = _parse_json3(raw)
        assert parsed.text == ""
        assert parsed.segments is None


# --- fetch_transcript / 429 backoff -----------------------------------------


def _info_with_track() -> dict[str, Any]:
    return {"subtitles": {"en": _formats("manual-en", "json3")}, "automatic_captions": {}}


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(transcripts.time, "sleep", sleeps.append)
    return sleeps


def test_fetch_transcript_without_info_raises_without_downloading(monkeypatch):
    def fail(url):
        raise AssertionError("must not download")

    monkeypatch.setattr(youtube_client, "fetch_url", fail)
    with pytest.raises(TranscriptError):
        fetch_transcript(None, "vid", ["en"])
    with pytest.raises(TranscriptError):
        fetch_transcript({"subtitles": {}, "automatic_captions": {}}, "vid", ["en"])


def test_fetch_transcript_downloads_selected_track(monkeypatch, no_sleep):
    calls: list[str] = []

    def fake_fetch(url):
        calls.append(url)
        return _json3("Hello", "world").encode()

    monkeypatch.setattr(youtube_client, "fetch_url", fake_fetch)
    assert fetch_transcript(_info_with_track(), "vid", ["en"]).text == "Hello world"
    assert calls == [_url("manual-en")]
    assert no_sleep == []


def test_fetch_transcript_retries_once_after_429(monkeypatch, no_sleep):
    attempts = iter([YouTubeRateLimitError("429"), _json3("ok").encode()])

    def fake_fetch(url):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(youtube_client, "fetch_url", fake_fetch)
    assert fetch_transcript(_info_with_track(), "vid", ["en"]).text == "ok"
    assert no_sleep == [transcripts._RATE_LIMIT_BACKOFF_SECONDS]


def test_fetch_transcript_gives_up_after_second_429(monkeypatch, no_sleep):
    def fake_fetch(url):
        raise YouTubeRateLimitError("429")

    monkeypatch.setattr(youtube_client, "fetch_url", fake_fetch)
    with pytest.raises(YouTubeRateLimitError):
        fetch_transcript(_info_with_track(), "vid", ["en"])
    assert no_sleep == [transcripts._RATE_LIMIT_BACKOFF_SECONDS]


def test_fetch_transcript_wraps_other_request_errors(monkeypatch, no_sleep):
    def fake_fetch(url):
        raise RequestError(msg="boom")

    monkeypatch.setattr(youtube_client, "fetch_url", fake_fetch)
    with pytest.raises(TranscriptError):
        fetch_transcript(_info_with_track(), "vid", ["en"])
    assert no_sleep == []


def test_fetch_transcript_empty_captions_raise(monkeypatch, no_sleep):
    monkeypatch.setattr(youtube_client, "fetch_url", lambda url: _json3().encode())
    with pytest.raises(TranscriptError):
        fetch_transcript(_info_with_track(), "vid", ["en"])


# --- segments / timestamped rendering ---------------------------------------


def _json3_timed(*events: tuple[int, str]) -> str:
    return json.dumps(
        {"events": [{"tStartMs": at, "segs": [{"utf8": text}]} for at, text in events]}
    )


def test_parse_json3_keeps_segment_start_times():
    parsed = _parse_json3(_json3_timed((0, "hello"), (1500, "world")))
    assert parsed.text == "hello world"
    assert parsed.segments == [
        transcripts.Segment(start_ms=0, text="hello"),
        transcripts.Segment(start_ms=1500, text="world"),
    ]


def test_render_timestamped_groups_into_windows():
    segments = [
        transcripts.Segment(start_ms=0, text="one"),
        transcripts.Segment(start_ms=10_000, text="two"),
        transcripts.Segment(start_ms=45_000, text="three"),
        transcripts.Segment(start_ms=3_700_000, text="four"),
    ]
    assert transcripts.render_timestamped(segments).splitlines() == [
        "[00:00] one two",
        "[00:45] three",
        "[1:01:40] four",
    ]


def test_rendered_falls_back_to_flat_text_without_segments():
    flat = transcripts.Transcript(text="flat")
    assert flat.rendered(timestamps=True) == "flat"


def test_segments_json_round_trip():
    segments = [transcripts.Segment(start_ms=250, text="a b")]
    assert transcripts.segments_from_json(transcripts.segments_to_json(segments)) == segments
    assert transcripts.segments_to_json([]) is None
    assert transcripts.segments_from_json(None) is None
    assert transcripts.segments_from_json("not json") is None
