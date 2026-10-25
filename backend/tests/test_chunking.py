"""Chunk building and the FTS5 query escaping that user input goes through."""

from __future__ import annotations

from yt_summarizer.chunking import build_chunks, fts_query
from yt_summarizer.transcripts import Segment


def test_segments_become_windowed_chunks_with_start_times():
    segments = [
        Segment(start_ms=0, text="one"),
        Segment(start_ms=30_000, text="two"),
        Segment(start_ms=61_000, text="three"),
    ]
    chunks = build_chunks("one two three", segments, "the summary")
    assert [(c.kind, c.text, c.start_seconds) for c in chunks] == [
        ("transcript", "one two", 0),
        ("transcript", "three", 61),
        ("summary", "the summary", None),
    ]


def test_flat_transcripts_chunk_by_word_count_without_timestamps():
    text = " ".join(str(index) for index in range(450))
    chunks = build_chunks(text, None, "")
    assert [c.kind for c in chunks] == ["transcript"] * 3
    assert all(c.start_seconds is None for c in chunks)
    assert chunks[0].text.split()[0] == "0"
    assert chunks[-1].text.split()[-1] == "449"


def test_empty_summary_adds_no_chunk():
    assert [c.kind for c in build_chunks("hello", None, "   ")] == ["transcript"]


def test_fts_query_quotes_tokens_and_prefixes_the_last():
    assert fts_query("bitcoin eth") == '"bitcoin" "eth"*'


def test_fts_query_keeps_phrases_unprefixed():
    assert fts_query('"going up"') == '"going up"'


def test_fts_query_strips_operators_and_punctuation():
    assert fts_query("bitcoin OR (NEAR") == '"bitcoin" "OR" "NEAR"*'
    assert fts_query('" AND *') == '"AND"*'
    assert fts_query("ada`s \"road map\" delays") == '"ada s" "road map" "delays"*'
    assert fts_query("   ") is None
    assert fts_query("*") is None
