"""What the frontend needs up front: the models on offer and the monitor's state."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from yt_summarizer.config import Settings
from yt_summarizer.models import ClaudeModel

from ..schemas import MetaOut, ModelOut

router = APIRouter()


def _to_model(model: ClaudeModel, settings: Settings) -> ModelOut:
    return ModelOut(
        family=model.family,
        id=model.id,
        name=model.name,
        efforts=list(model.efforts),
        price_confirmed=settings.priced_models.get(model.family) == model.alias,
    )


def _utc_midnight_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


@router.get("/api/meta", response_model=MetaOut)
def get_meta(request: Request) -> MetaOut:
    state = request.app.state
    cfg = state.settings.current
    # The schedule fires in local time, but every timestamp we serve is UTC.
    next_run = state.monitor.next_run_at
    return MetaOut(
        models=[_to_model(model, cfg) for model in state.catalog.models()],
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


@router.post("/api/models/refresh", response_model=list[ModelOut])
def refresh_models(request: Request) -> list[ModelOut]:
    state = request.app.state
    models = state.catalog.refresh()
    return [_to_model(model, state.settings.current) for model in models]
