"""The monitor and user-initiated jobs share one single-job slot."""

from __future__ import annotations

import time

import pytest

from app.estimates import PreparedEstimate, PreparedVideo
from app.jobs import JobConflictError, JobRegistry
from yt_summarizer.claude_client import CostEstimate, ModelSettings, SummaryResult
from yt_summarizer.config import ModelPricing
from yt_summarizer.database import Database
from yt_summarizer.transcripts import Transcript
from yt_summarizer.youtube_client import Video


def _empty_estimate() -> PreparedEstimate:
    return PreparedEstimate(
        estimate_id="e",
        channel_id=1,
        prompt_name="p",
        prompt_text="t",
        settings=ModelSettings("m", "low", 8192, ModelPricing(1.0, 5.0)),
        extraction=None,
        items={},
    )


def test_reserve_for_monitor_blocks_second_reservation():
    reg = JobRegistry()
    assert reg.reserve_for_monitor() is True
    assert reg.has_running_job() is True
    assert reg.reserve_for_monitor() is False  # already held
    reg.release_monitor()
    assert reg.has_running_job() is False
    assert reg.reserve_for_monitor() is True  # free again


def test_user_job_rejected_while_monitor_reserved():
    reg = JobRegistry()
    assert reg.reserve_for_monitor() is True
    # start() builds the Job then checks the shared slot before spawning a thread.
    with pytest.raises(JobConflictError):
        reg.start(_empty_estimate(), [], db=None, summarizer=None)  # type: ignore[arg-type]


class _Summarizer:
    def summarize(self, settings, prompt, transcript, extraction=None) -> SummaryResult:
        return SummaryResult(
            text="A summary",
            tokens_input=1000,
            tokens_output=500,
            cost_usd=0.1,
            stop_reason="max_tokens",
            tokens_thinking=320,
            duration_ms=900,
        )


def test_job_saves_the_summary_with_its_run_stats(tmp_path):
    db = Database(tmp_path / "v.db")
    video = Video(video_id="v0", title="T", published_at=None, url="https://y/v0")
    estimate = PreparedEstimate(
        estimate_id="e",
        channel_id=1,
        prompt_name="p",
        prompt_text="t",
        settings=ModelSettings("m", "xhigh", 500, ModelPricing(1.0, 5.0)),
        extraction=None,
        items={
            "v0": PreparedVideo(
                video=video,
                transcript=Transcript(text="words", source="manual"),
                estimate=CostEstimate(
                    input_tokens=1000, estimated_output_tokens=2500, cost_usd=0.2
                ),
            )
        },
    )
    reg = JobRegistry()

    job = reg.start(estimate, ["v0"], db, _Summarizer())  # type: ignore[arg-type]
    deadline = time.monotonic() + 5
    while reg.snapshot(job.job_id).status != "done" and time.monotonic() < deadline:
        time.sleep(0.01)

    row = db.get_summary("v0")
    assert (row["model"], row["effort"], row["max_output_tokens"]) == ("m", "xhigh", 500)
    assert (row["estimated_output_tokens"], row["tokens_thinking"]) == (2500, 320)
    assert (row["stop_reason"], row["duration_ms"]) == ("max_tokens", 900)
    assert row["transcript_source"] == "manual"
