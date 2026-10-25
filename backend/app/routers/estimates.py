"""Token/cost estimation for a batch of selected videos (free — no billing)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from yt_summarizer import transcripts, youtube_client
from yt_summarizer.transcripts import Transcript
from yt_summarizer.youtube_client import RATE_LIMITED_MESSAGE, Video, YouTubeRateLimitError

from ..estimates import PreparedVideo
from ..prompts import extraction_for, settings_for
from ..schemas import EstimateItemOut, EstimateOut, EstimateRequest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/estimates")


@router.post("", response_model=EstimateOut)
def create_estimate(body: EstimateRequest, request: Request) -> EstimateOut:
    state = request.app.state
    cfg = state.settings.current

    channel = state.db.get_channel(body.channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    prompt = (
        state.db.get_prompt_by_name(channel["prompt_name"]) if channel["prompt_name"] else None
    )
    if prompt is None:
        raise HTTPException(
            status_code=422,
            detail="This channel has no prompt. Choose one in Channels.",
        )
    prompt_name = prompt["name"]
    settings = settings_for(prompt, state.catalog, cfg.pricing)
    if settings is None:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt {prompt_name!r} needs a model and an effort. Choose them in Prompts.",
        )
    prompt_text = prompt["text"]
    estimated_output_tokens = prompt["estimated_output_tokens"]
    extraction = extraction_for(state.db, prompt)

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
            transcript = Transcript(
                text=row["transcript"],
                segments=transcripts.segments_from_json(row["transcript_segments"]),
                source=row["transcript_source"],
            )
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
                    detail=RATE_LIMITED_MESSAGE,
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
                        detail=RATE_LIMITED_MESSAGE,
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
        estimate = state.summarizer.estimate(
            settings, prompt_text, transcript, estimated_output_tokens, extraction
        )
        prepared[video_id] = PreparedVideo(video=video, transcript=transcript, estimate=estimate)
        items.append(
            EstimateItemOut(
                video_id=video_id,
                title=video.title,
                published_at=video.published_at,
                url=video.url,
                status="ok",
                transcript_source=transcript.source,
                input_tokens=estimate.input_tokens,
                estimated_output_tokens=estimate.estimated_output_tokens,
                cost_usd=estimate.cost_usd,
            )
        )

    estimate_id = state.estimates.put(
        channel_id=body.channel_id,
        prompt_name=prompt_name,
        prompt_text=prompt_text,
        settings=settings,
        extraction=extraction,
        items=prepared,
    )

    total_input = sum(item.estimate.input_tokens for item in prepared.values())
    total_cost = sum(item.estimate.cost_usd for item in prepared.values())

    return EstimateOut(
        estimate_id=estimate_id,
        model=settings.model,
        effort=settings.effort,
        prompt_name=prompt_name,
        items=items,
        total_input_tokens=total_input,
        total_cost_usd=total_cost,
    )
