"""Stored summaries: listing and detail (with transcript)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..schemas import MentionOut, SummaryDetailOut, SummaryOut

router = APIRouter(prefix="/api/summaries")


@router.get("", response_model=list[SummaryOut])
def list_summaries(request: Request, channel_id: int | None = None) -> list[SummaryOut]:
    db = request.app.state.db
    rows = db.all_summaries(channel_id)
    mentions = db.mentions_for_videos([row["video_id"] for row in rows])
    summaries = []
    for row in rows:
        data = dict(row)
        data["mentions"] = [
            MentionOut.model_validate(dict(m)) for m in mentions.get(row["video_id"], [])
        ]
        summaries.append(SummaryOut.model_validate(data))
    return summaries


@router.get("/{video_id}", response_model=SummaryDetailOut)
def get_summary(video_id: str, request: Request) -> SummaryDetailOut:
    db = request.app.state.db
    row = db.get_summary(video_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    data = dict(row)
    data["mentions"] = [
        MentionOut.model_validate(dict(m))
        for m in db.mentions_for_videos([video_id]).get(video_id, [])
    ]
    return SummaryDetailOut.model_validate(data)


@router.delete("/{video_id}", status_code=204)
def delete_summary(video_id: str, request: Request) -> None:
    """Drop a stored summary (and its transcript). The video can be redone."""
    if not request.app.state.db.delete_summary(video_id):
        raise HTTPException(status_code=404, detail="Summary not found")
