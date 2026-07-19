"""Token/cost estimation for a batch of selected videos (free — no billing)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from yt_summarizer import transcripts, youtube_client
from yt_summarizer.youtube_client import Video, YouTubeRateLimitError

from ..estimates import PreparedVideo
from ..schemas import EstimateItemOut, EstimateOut, EstimateRequest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/estimates")

_RATE_LIMITED_DETAIL = "YouTube rate limit (HTTP 429) — wait a few minutes and retry."
_SKIPPED_DETAIL = "Skipped — YouTube is rate limiting this IP; try again in a few minutes."


@router.post("", response_model=EstimateOut)
def create_estimate(body: EstimateRequest, request: Request) -> EstimateOut:
    state = request.app.state
    cfg = state.config

    if state.db.get_channel(body.channel_id) is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    prompt_name = body.prompt_name or cfg.active_prompt
    if prompt_name not in cfg.prompts:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown prompt {prompt_name!r} (available: {', '.join(cfg.prompts)})",
        )
    prompt_text = cfg.prompts[prompt_name]

    prepared: dict[str, PreparedVideo] = {}
    items: list[EstimateItemOut] = []
    rate_limited = False
    for video_id in dict.fromkeys(body.video_ids):  # de-duplicate, keep order
        video = Video(
            video_id=video_id,
            title=video_id,
            published_at=None,
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

        row = state.db.get_summary(video_id)
        if row is not None and row["transcript"]:
            # Already summarized once — reuse the stored transcript and
            # metadata instead of asking YouTube again.
            log.info("Reusing stored transcript for %s", video_id)
            video = Video(
                video_id=video_id,
                title=row["title"],
                published_at=row["published_at"],
                url=row["url"],
            )
            transcript = row["transcript"]
        elif rate_limited:
            # YouTube already answered 429 in this batch; don't dig a deeper
            # hole by requesting the remaining videos.
            items.append(
                EstimateItemOut(
                    video_id=video_id,
                    title=video.title,
                    published_at=video.published_at,
                    url=video.url,
                    status="no_transcript",
                    detail=_SKIPPED_DETAIL,
                )
            )
            continue
        else:
            try:
                video, info = youtube_client.fetch_video_details(video)
                transcript = transcripts.fetch_transcript(
                    info, video_id, cfg.transcript_languages
                )
            except YouTubeRateLimitError:
                rate_limited = True
                items.append(
                    EstimateItemOut(
                        video_id=video_id,
                        title=video.title,
                        published_at=video.published_at,
                        url=video.url,
                        status="no_transcript",
                        detail=_RATE_LIMITED_DETAIL,
                    )
                )
                continue
            except transcripts.TranscriptError as exc:
                items.append(
                    EstimateItemOut(
                        video_id=video_id,
                        title=video.title,
                        published_at=video.published_at,
                        url=video.url,
                        status="no_transcript",
                        detail=str(exc),
                    )
                )
                continue

        # Auth/model errors would fail for every video — let the whole request
        # abort with a 502 via the SummarizerError handler.
        estimate = state.summarizer.estimate(prompt_text, transcript, cfg.estimated_output_tokens)
        prepared[video_id] = PreparedVideo(video=video, transcript=transcript, estimate=estimate)
        items.append(
            EstimateItemOut(
                video_id=video_id,
                title=video.title,
                published_at=video.published_at,
                url=video.url,
                status="ok",
                input_tokens=estimate.input_tokens,
                estimated_output_tokens=estimate.estimated_output_tokens,
                cost_usd=estimate.cost_usd,
            )
        )

    estimate_id = state.estimates.put(
        channel_id=body.channel_id,
        prompt_name=prompt_name,
        prompt_text=prompt_text,
        items=prepared,
    )

    total_input = sum(item.estimate.input_tokens for item in prepared.values())
    total_cost: float | None = 0.0
    for item in prepared.values():
        if item.estimate.cost_usd is None:
            total_cost = None
            break
        total_cost += item.estimate.cost_usd

    return EstimateOut(
        estimate_id=estimate_id,
        model=cfg.model,
        prompt_name=prompt_name,
        items=items,
        total_input_tokens=total_input,
        total_cost_usd=total_cost,
    )
