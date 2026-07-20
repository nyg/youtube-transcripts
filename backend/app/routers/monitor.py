"""Manual trigger for one monitor cycle (useful for testing without waiting)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import MonitorRunOut

router = APIRouter(prefix="/api/monitor")


@router.post("/run", response_model=MonitorRunOut)
def run_now(request: Request) -> MonitorRunOut:
    """Kick off one monitor cycle in the background.

    Works regardless of whether the scheduler is enabled, so the pipeline can be
    exercised on demand. Returns immediately; a cycle already in progress (or a
    running summarization job) is reported via `started: false`.
    """
    state = request.app.state
    if state.jobs.has_running_job():
        return MonitorRunOut(
            started=False,
            detail="A summarization job or monitor cycle is already running — try again shortly.",
        )
    state.monitor.trigger_async()
    return MonitorRunOut(started=True, detail="Monitor cycle started.")
