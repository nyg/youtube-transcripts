"""Context assembly for cross-video questions: what goes in, in what order,
and that the budget is respected."""

from __future__ import annotations

from yt_summarizer.analysis import build_context, search_terms
from yt_summarizer.database import Database
from yt_summarizer.mentions import Mention
from yt_summarizer.transcripts import Segment, segments_to_json


def _save(db: Database, video_id: str, published_at: str, summary: str, transcript: str) -> None:
    db.save_summary(
        video_id=video_id,
        title=f"Video {video_id}",
        url=f"https://www.youtube.com/watch?v={video_id}",
        published_at=published_at,
        transcript=transcript,
        prompt_name="crypto",
        model="m",
        ai_response=summary,
        tokens_input=1,
        tokens_output=1,
        cost_usd=0.01,
        channel_id=1,
        transcript_segments=segments_to_json([Segment(start_ms=120_000, text=transcript)]),
        mentions=[
            Mention("Cardano", "bearish", "high", "Roadmap delays.", "ada keeps missing", 120)
        ],
    )


def test_context_numbers_mentions_then_summaries_then_excerpts(tmp_path):
    db = Database(tmp_path / "v.db")
    _save(db, "v0", "2026-09-10T10:00:00+00:00", "Cardano is late", "cardano keeps missing deadlines")

    context = build_context(db, "What about cardano deadlines?", channel_id=1)

    assert [source.kind for source in context.sources] == ["mention", "summary", "excerpt"]
    assert [source.number for source in context.sources] == [1, 2, 3]
    assert context.mention_count == 1
    assert context.summary_count == 1
    assert context.excerpt_count == 1
    assert "[1] mention · 2026-09-10 · Video v0 @ 02:00" in context.text
    assert "Cardano: bearish (high confidence)" in context.text
    assert "[2] summary" in context.text and "Cardano is late" in context.text
    assert "[3] excerpt" in context.text
    assert context.sources[0].start_seconds == 120


def test_context_respects_the_date_range_and_channel(tmp_path):
    db = Database(tmp_path / "v.db")
    _save(db, "old", "2026-06-01T10:00:00+00:00", "Old take", "cardano was fine then")
    _save(db, "new", "2026-09-10T10:00:00+00:00", "New take", "cardano keeps missing deadlines")

    context = build_context(db, "cardano?", channel_id=1, since="2026-09-01T00:00:00+00:00")

    assert {source.video_id for source in context.sources} == {"new"}
    assert build_context(db, "cardano?", channel_id=99).sources == []


def test_context_stops_at_the_token_budget(tmp_path):
    db = Database(tmp_path / "v.db")
    for index in range(5):
        _save(
            db,
            f"v{index}",
            f"2026-09-0{index + 1}T10:00:00+00:00",
            "word " * 500,
            "cardano " * 500,
        )

    context = build_context(db, "cardano?", channel_id=1, max_tokens=1000)

    assert len(context.text) <= 1000 * 4
    assert context.sources


def test_search_terms_drops_question_words():
    assert search_terms("What did he say about Solana this month?") == "Solana"
    assert search_terms("is it up?") == ""
