"""Stored summaries: listing and detail (with transcript)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..schemas import SummaryDetailOut, SummaryOut

router = APIRouter(prefix="/api/summaries")


@router.get("", response_model=list[SummaryOut])
def list_summaries(request: Request, channel_id: int | None = None) -> list[SummaryOut]:
    rows = request.app.state.db.all_summaries(channel_id)
    return [SummaryOut.model_validate(dict(row)) for row in rows]


@router.get("/{video_id}", response_model=SummaryDetailOut)
def get_summary(video_id: str, request: Request) -> SummaryDetailOut:
    row = request.app.state.db.get_summary(video_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    return SummaryDetailOut.model_validate(dict(row))
