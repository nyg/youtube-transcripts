"""Summarization jobs: creation (consumes an estimate) and status polling."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..jobs import JobConflictError
from ..schemas import JobCreate, JobCreated, JobOut

router = APIRouter(prefix="/api/jobs")


@router.post("", response_model=JobCreated, status_code=201)
def create_job(body: JobCreate, request: Request) -> JobCreated:
    state = request.app.state

    if state.jobs.has_running_job():
        raise HTTPException(status_code=409, detail="A summarization job is already running")

    estimate = state.estimates.pop(body.estimate_id)
    if estimate is None:
        raise HTTPException(
            status_code=410,
            detail="This estimate has expired or was already used — please re-run it",
        )

    video_ids = body.video_ids if body.video_ids is not None else list(estimate.items)
    unknown = [video_id for video_id in video_ids if video_id not in estimate.items]
    if unknown or not video_ids:
        state.estimates.restore(estimate)
        detail = (
            f"Video ids not part of the estimate: {', '.join(unknown)}"
            if unknown
            else "No videos to process"
        )
        raise HTTPException(status_code=422, detail=detail)

    try:
        job = state.jobs.start(estimate, video_ids, state.db, state.summarizer)
    except JobConflictError:
        state.estimates.restore(estimate)
        raise HTTPException(status_code=409, detail="A summarization job is already running")
    return JobCreated(job_id=job.job_id)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request) -> JobOut:
    snapshot = request.app.state.jobs.snapshot(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return snapshot
