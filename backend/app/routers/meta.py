"""Read-only endpoint exposing config values the frontend needs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..schemas import MetaOut

router = APIRouter()


def _utc_midnight_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


@router.get("/api/meta", response_model=MetaOut)
def get_meta(request: Request) -> MetaOut:
    state = request.app.state
    cfg = state.config
    return MetaOut(
        model=cfg.model,
        prompts=list(cfg.prompts),
        active_prompt=cfg.active_prompt,
        estimated_output_tokens=cfg.estimated_output_tokens,
        max_videos_fetch=cfg.max_videos_fetch,
        monitoring_enabled=cfg.monitor.enabled,
        daily_budget_usd=cfg.monitor.daily_budget_usd,
        spend_today_usd=state.db.spend_since(_utc_midnight_iso()),
    )
