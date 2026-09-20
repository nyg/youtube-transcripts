"""The monitor and user-initiated jobs share one single-job slot."""

from __future__ import annotations

import pytest

from app.estimates import PreparedEstimate
from app.jobs import JobConflictError, JobRegistry


def _empty_estimate() -> PreparedEstimate:
    return PreparedEstimate(
        estimate_id="e",
        channel_id=1,
        prompt_name="p",
        prompt_text="t",
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
        reg.start(_empty_estimate(), [], db=None, summarizer=None, model="m")  # type: ignore[arg-type]
