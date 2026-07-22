"""ChannelMonitor: budget gate, age filter, mutex, per-channel prompt + email."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.jobs import JobRegistry
from app.monitor import ChannelMonitor
from yt_summarizer import notifications, transcripts, youtube_client
from yt_summarizer.claude_client import CostEstimate, SummaryResult
from yt_summarizer.config import Config, MonitorConfig
from yt_summarizer.database import Database
from yt_summarizer.youtube_client import Video


class FakeSummarizer:
    """Fixed worst-case and actual cost so budget math is deterministic."""

    max_output_tokens = 8192

    def __init__(self, worst: float, actual: float) -> None:
        self._worst = worst
        self._actual = actual
        self.summarize_calls = 0

    def estimate(self, prompt: str, transcript: str, estimated_output_tokens: int) -> CostEstimate:
        return CostEstimate(input_tokens=1000, estimated_output_tokens=estimated_output_tokens,
                            cost_usd=0.01)

    def cost(self, tokens_input: int, tokens_output: int) -> float:
        return self._worst

    def summarize(self, prompt: str, transcript: str) -> SummaryResult:
        self.summarize_calls += 1
        return SummaryResult(text="A summary", tokens_input=1000, tokens_output=500,
                             cost_usd=self._actual, stop_reason="end_turn")


def _make_config(
    db_path: Path,
    *,
    enabled: bool = True,
    max_videos_check: int = 5,
    max_age_hours: int = 0,
    daily_budget_usd: float = 1.0,
) -> Config:
    mon = MonitorConfig(
        enabled=enabled,
        interval_minutes=60,
        max_videos_check=max_videos_check,
        max_age_hours=max_age_hours,
        daily_budget_usd=daily_budget_usd,
        resend_from="from@example.com",
        subject_prefix="New video summaries",
    )
    return Config(
        max_videos_fetch=25, transcript_languages=("en",),
        youtube_request_interval=0.0, cookies_file=None, model="claude-test",
        max_output_tokens=8192, pricing={},
        database=db_path, monitor=mon,
    )


def _seed_channel(db: Database, *, prompt="default", text="sys", recipients=None):
    """Add a prompt (once) and a channel referencing it. Prompts now live in the DB."""
    if db.get_prompt_by_name(prompt) is None:
        db.add_prompt(prompt, text, 2000)
    return db.add_channel("@chan", "Chan", prompt, recipients or [])


def _video(vid: str, published_at: str | None) -> Video:
    return Video(video_id=vid, title=f"Title {vid}", published_at=published_at,
                 url=f"https://youtu.be/{vid}")


def _patch_youtube(monkeypatch, videos: list[Video]) -> None:
    monkeypatch.setattr(youtube_client, "list_recent_videos", lambda inp, n: videos)
    monkeypatch.setattr(youtube_client, "fetch_video_details", lambda v: (v, {"info": True}))
    monkeypatch.setattr(transcripts, "fetch_transcript", lambda info, vid, langs: "transcript")


def test_budget_gate_defers_remaining(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db)
    _patch_youtube(monkeypatch, [_video("v0", None), _video("v1", None), _video("v2", None)])
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=1.00, max_age_hours=0)
    summarizer = FakeSummarizer(worst=0.60, actual=0.50)

    result = ChannelMonitor(cfg, db, summarizer, JobRegistry()).run_cycle()

    # v0: 0 + 0.60 <= 1.00 -> summarized (spend 0.50).
    # v1: 0.50 + 0.60 = 1.10 > 1.00 -> deferred.
    assert result.summarized == 1
    assert result.budget_hit is True
    assert result.spent_today == pytest.approx(0.50)
    assert db.processed_ids() == {"v0"}


def test_no_budget_processes_all(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db)
    _patch_youtube(monkeypatch, [_video("v0", None), _video("v1", None), _video("v2", None)])
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=0.0, max_age_hours=0)  # 0 = unlimited

    result = ChannelMonitor(cfg, db, FakeSummarizer(0.60, 0.50), JobRegistry()).run_cycle()

    assert result.summarized == 3
    assert result.budget_hit is False
    assert db.processed_ids() == {"v0", "v1", "v2"}


def test_deferred_videos_processed_on_next_cycle_with_headroom(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db)
    _patch_youtube(monkeypatch, [_video("v0", None), _video("v1", None)])
    # First cycle: tiny budget only fits one video.
    cfg_small = _make_config(tmp_path / "v.db", daily_budget_usd=0.60, max_age_hours=0)
    ChannelMonitor(cfg_small, db, FakeSummarizer(0.60, 0.50), JobRegistry()).run_cycle()
    assert db.processed_ids() == {"v0"}

    # Next cycle with a higher cap picks up the deferred one (v0 already done).
    cfg_big = _make_config(tmp_path / "v.db", daily_budget_usd=100.0, max_age_hours=0)
    result = ChannelMonitor(cfg_big, db, FakeSummarizer(0.60, 0.50), JobRegistry()).run_cycle()
    assert result.summarized == 1
    assert db.processed_ids() == {"v0", "v1"}


def test_age_filter_skips_old_and_undated(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db)
    now = datetime.now(timezone.utc)
    recent = _video("recent", (now - timedelta(hours=1)).isoformat(timespec="seconds"))
    old = _video("old", (now - timedelta(hours=100)).isoformat(timespec="seconds"))
    undated = _video("undated", None)
    _patch_youtube(monkeypatch, [recent, old, undated])
    cfg = _make_config(tmp_path / "v.db", max_age_hours=48, daily_budget_usd=0.0)

    ChannelMonitor(cfg, db, FakeSummarizer(0.10, 0.10), JobRegistry()).run_cycle()

    assert db.processed_ids() == {"recent"}


def test_skips_cycle_when_slot_reserved(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db)
    _patch_youtube(monkeypatch, [_video("v0", None)])
    jobs = JobRegistry()
    assert jobs.reserve_for_monitor() is True  # simulate a running job
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=0.0)

    result = ChannelMonitor(cfg, db, FakeSummarizer(0.1, 0.1), jobs).run_cycle()

    assert result.skipped is True
    assert db.processed_ids() == set()


def test_per_channel_prompt_is_used(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    db.add_prompt("alt", "alt sys", 2000)
    db.add_channel("@chan", "Chan", "alt")
    _patch_youtube(monkeypatch, [_video("v0", None)])
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=0.0)

    seen: dict[str, str] = {}

    class RecordingSummarizer(FakeSummarizer):
        def summarize(self, prompt: str, transcript: str) -> SummaryResult:
            seen["prompt"] = prompt
            return super().summarize(prompt, transcript)

    ChannelMonitor(cfg, db, RecordingSummarizer(0.1, 0.1), JobRegistry()).run_cycle()

    assert seen["prompt"] == "alt sys"  # the channel's "alt" prompt text


def test_channel_without_prompt_is_skipped(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    db.add_channel("@chan", "Chan")  # no prompt assigned
    _patch_youtube(monkeypatch, [_video("v0", None)])
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=0.0)

    result = ChannelMonitor(cfg, db, FakeSummarizer(0.1, 0.1), JobRegistry()).run_cycle()

    assert result.summarized == 0
    assert db.processed_ids() == set()


def test_email_sent_with_summaries(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db, recipients=["me@example.com"])
    _patch_youtube(monkeypatch, [_video("v0", None)])
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=0.0)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    captured: dict[str, object] = {}

    def fake_send(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(notifications, "send_email", fake_send)

    ChannelMonitor(cfg, db, FakeSummarizer(0.1, 0.1), JobRegistry()).run_cycle()

    assert captured["recipients"] == ["me@example.com"]
    assert "A summary" in captured["html"]  # type: ignore[operator]
    assert captured["sender"] == "from@example.com"


def test_no_email_when_channel_has_no_recipients(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db, recipients=[])  # summarized, but nobody to email
    _patch_youtube(monkeypatch, [_video("v0", None)])
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=0.0)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    sends: list[dict] = []
    monkeypatch.setattr(notifications, "send_email", lambda **kw: sends.append(kw))

    result = ChannelMonitor(cfg, db, FakeSummarizer(0.1, 0.1), JobRegistry()).run_cycle()

    assert result.summarized == 1
    assert sends == []


def test_digest_grouped_per_channel(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    db.add_prompt("default", "sys", 2000)
    db.add_channel("@a", "A", "default", ["a@example.com"])
    db.add_channel("@b", "B", "default", ["b@example.com"])
    per_channel = {"@a": [_video("va", None)], "@b": [_video("vb", None)]}
    monkeypatch.setattr(youtube_client, "list_recent_videos", lambda inp, n: per_channel[inp])
    monkeypatch.setattr(youtube_client, "fetch_video_details", lambda v: (v, {"info": True}))
    monkeypatch.setattr(transcripts, "fetch_transcript", lambda info, vid, langs: "transcript")
    cfg = _make_config(tmp_path / "v.db", daily_budget_usd=0.0)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    sends: list[dict] = []
    monkeypatch.setattr(notifications, "send_email", lambda **kw: sends.append(kw))

    ChannelMonitor(cfg, db, FakeSummarizer(0.1, 0.1), JobRegistry()).run_cycle()

    # One digest per channel, each to its own recipients.
    assert len(sends) == 2
    assert {s["recipients"][0] for s in sends} == {"a@example.com", "b@example.com"}


def test_no_email_when_nothing_new(tmp_path, monkeypatch):
    db = Database(tmp_path / "v.db")
    _seed_channel(db, recipients=["me@example.com"])
    _patch_youtube(monkeypatch, [])  # no videos
    cfg = _make_config(tmp_path / "v.db")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    calls = []
    monkeypatch.setattr(notifications, "send_email", lambda **kw: calls.append(kw))

    result = ChannelMonitor(cfg, db, FakeSummarizer(0.1, 0.1), JobRegistry()).run_cycle()

    assert result.summarized == 0
    assert calls == []
