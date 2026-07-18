"""Read-only endpoint exposing config values the frontend needs."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import MetaOut

router = APIRouter()


@router.get("/api/meta", response_model=MetaOut)
def get_meta(request: Request) -> MetaOut:
    cfg = request.app.state.config
    return MetaOut(
        model=cfg.model,
        prompts=list(cfg.prompts),
        active_prompt=cfg.active_prompt,
        estimated_output_tokens=cfg.estimated_output_tokens,
        max_videos_fetch=cfg.max_videos_fetch,
    )
