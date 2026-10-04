"""Read-only endpoint exposing config values the frontend needs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from yt_summarizer.claude_client import EFFORT_LEVELS

from ..schemas import MetaOut

router = APIRouter()


def _utc_midnight_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


@router.get("/api/meta", response_model=MetaOut)
def get_meta(request: Request) -> MetaOut:
    state = request.app.state
    cfg = state.config
    # The schedule fires in local time, but every timestamp we serve is UTC.
    next_run = state.monitor.next_run_at
    return MetaOut(
        models=list(cfg.pricing),
        efforts=list(EFFORT_LEVELS),
        max_videos_fetch=cfg.max_videos_fetch,
        monitoring_enabled=cfg.monitor.enabled,
        monitor_schedule=cfg.monitor.schedule,
        monitor_next_run=(
            next_run.astimezone(timezone.utc).isoformat(timespec="seconds")
            if next_run
            else None
        ),
        daily_budget_usd=cfg.monitor.daily_budget_usd,
        spend_today_usd=state.db.spend_since(_utc_midnight_iso()),
    )
