"""In-memory job registry and the background summarization worker."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from yt_summarizer.claude_client import ClaudeSummarizer, Extraction, SummarizerError
from yt_summarizer.database import Database
from yt_summarizer.transcripts import Transcript, segments_to_json
from yt_summarizer.youtube_client import Video

from .estimates import PreparedEstimate
from .schemas import JobItemOut, JobOut

log = logging.getLogger(__name__)


class JobConflictError(Exception):
    """Raised when a job is requested while another one is still running."""


@dataclass
class JobItem:
    video: Video
    transcript: Transcript
    status: str = "queued"  # queued | processing | done | failed
    error: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float | None = None


@dataclass
class Job:
    job_id: str
    channel_id: int
    prompt_name: str
    created_at: str
    items: list[JobItem]
    status: str = "running"  # running | done


class JobRegistry:
    """Jobs are kept for the process lifetime; only one may run at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        # Set while the background monitor is running a cycle. It shares the
        # single-job invariant with user-initiated jobs so the two never run
        # concurrently (see monitor.py).
        self._monitor_active = False

    def _busy(self) -> bool:
        return self._monitor_active or any(job.status == "running" for job in self._jobs.values())

    def has_running_job(self) -> bool:
        with self._lock:
            return self._busy()

    def reserve_for_monitor(self) -> bool:
        """Claim the single-job slot for the monitor. False if anything is running."""
        with self._lock:
            if self._busy():
                return False
            self._monitor_active = True
            return True

    def release_monitor(self) -> None:
        with self._lock:
            self._monitor_active = False

    def start(
        self,
        estimate: PreparedEstimate,
        video_ids: list[str],
        db: Database,
        summarizer: ClaudeSummarizer,
        model: str,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex,
            channel_id=estimate.channel_id,
            prompt_name=estimate.prompt_name,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            items=[
                JobItem(video=prepared.video, transcript=prepared.transcript)
                for video_id, prepared in estimate.items.items()
                if video_id in video_ids
            ],
        )
        with self._lock:
            if self._busy():
                raise JobConflictError("A summarization job is already running")
            self._jobs[job.job_id] = job
        thread = threading.Thread(
            target=self._run,
            args=(job, estimate.prompt_text, estimate.extraction, db, summarizer, model),
            name=f"job-{job.job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return job

    def snapshot(self, job_id: str) -> JobOut | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            items = [
                JobItemOut(
                    video_id=item.video.video_id,
                    title=item.video.title,
                    status=item.status,  # type: ignore[arg-type]
                    error=item.error,
                    tokens_input=item.tokens_input,
                    tokens_output=item.tokens_output,
                    cost_usd=item.cost_usd,
                )
                for item in job.items
            ]
            return JobOut(
                job_id=job.job_id,
                status=job.status,  # type: ignore[arg-type]
                created_at=job.created_at,
                items=items,
                total_cost_usd=sum(item.cost_usd or 0.0 for item in job.items),
            )

    def _run(
        self,
        job: Job,
        prompt_text: str,
        extraction: Extraction | None,
        db: Database,
        summarizer: ClaudeSummarizer,
        model: str,
    ) -> None:
        try:
            for item in job.items:
                with self._lock:
                    item.status = "processing"
                try:
                    result = summarizer.summarize(prompt_text, item.transcript, extraction)
                except SummarizerError as exc:
                    log.error("Failed to summarize %s: %s", item.video.video_id, exc)
                    with self._lock:
                        item.status = "failed"
                        item.error = str(exc)
                    continue
                db.save_summary(
                    video_id=item.video.video_id,
                    title=item.video.title,
                    url=item.video.url,
                    published_at=item.video.published_at,
                    transcript=item.transcript.text,
                    transcript_segments=segments_to_json(item.transcript.segments),
                    mentions=result.mentions,
                    prompt_name=job.prompt_name,
                    model=model,
                    ai_response=result.text,
                    tokens_input=result.tokens_input,
                    tokens_output=result.tokens_output,
                    cost_usd=result.cost_usd,
                    channel_id=job.channel_id,
                )
                with self._lock:
                    item.status = "done"
                    item.tokens_input = result.tokens_input
                    item.tokens_output = result.tokens_output
                    item.cost_usd = result.cost_usd
        except Exception:
            log.exception("Job %s crashed", job.job_id)
            with self._lock:
                for item in job.items:
                    if item.status in ("queued", "processing"):
                        item.status = "failed"
                        item.error = "Internal error — see server logs"
        finally:
            with self._lock:
                job.status = "done"
