"""Channel management and per-channel video listing."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from yt_summarizer import youtube_client

from ..schemas import ChannelIn, ChannelOut, ChannelPatch, VideoListOut, VideoOut

router = APIRouter(prefix="/api/channels")


def _to_channel(row: sqlite3.Row) -> ChannelOut:
    return ChannelOut(
        id=row["id"],
        input=row["input"],
        label=row["label"],
        created_at=row["created_at"],
        prompt_name=row["prompt_name"],
    )


def _validate_prompt(request: Request, prompt_name: str | None) -> None:
    if prompt_name is None:
        return
    prompts = request.app.state.config.prompts
    if prompt_name not in prompts:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown prompt {prompt_name!r} (available: {', '.join(prompts)})",
        )


@router.get("", response_model=list[ChannelOut])
def list_channels(request: Request) -> list[ChannelOut]:
    return [_to_channel(row) for row in request.app.state.db.list_channels()]


@router.post("", response_model=ChannelOut, status_code=201)
def add_channel(body: ChannelIn, request: Request) -> ChannelOut:
    channel_input = body.input.strip()
    _validate_prompt(request, body.prompt_name)
    label = youtube_client.probe_channel(channel_input)  # ValueError (empty) → 422 handler
    if label is None:
        raise HTTPException(
            status_code=422,
            detail=f"Could not find a YouTube channel for {channel_input!r} — "
            "expected an @handle, a UC... channel ID, or a channel URL",
        )
    try:
        row = request.app.state.db.add_channel(
            channel_input, body.label or label, body.prompt_name
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Channel {channel_input!r} already exists")
    return _to_channel(row)


@router.patch("/{channel_id}", response_model=ChannelOut)
def update_channel(channel_id: int, body: ChannelPatch, request: Request) -> ChannelOut:
    _validate_prompt(request, body.prompt_name)
    row = request.app.state.db.set_channel_prompt(channel_id, body.prompt_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _to_channel(row)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: int, request: Request) -> None:
    if not request.app.state.db.delete_channel(channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")


@router.get("/{channel_id}/videos", response_model=VideoListOut)
def list_videos(
    channel_id: int,
    request: Request,
    max: int | None = Query(default=None, ge=1, le=100),
) -> VideoListOut:
    state = request.app.state
    row = state.db.get_channel(channel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    videos = youtube_client.list_recent_videos(row["input"], max or state.config.max_videos_fetch)
    processed = state.db.processed_ids()
    # Already-processed videos have an exact publish date stored — prefer it over
    # the (possibly approximate) date from the listing.
    stored_dates = state.db.published_dates()

    def _out(video: youtube_client.Video) -> VideoOut:
        exact = stored_dates.get(video.video_id)
        return VideoOut(
            video_id=video.video_id,
            title=video.title,
            published_at=exact or video.published_at,
            url=video.url,
            processed=video.video_id in processed,
            date_approximate=video.date_is_approximate and exact is None,
        )

    return VideoListOut(
        channel=_to_channel(row),
        videos=[_out(video) for video in videos],
    )
