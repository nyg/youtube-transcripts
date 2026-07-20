"""Background monitor: hourly checks for new videos, auto-summarize, email digest.

Runs inside the FastAPI process as a daemon thread (started/stopped in the app
lifespan). One "cycle" per interval:

  discover new videos per channel  ->  budget-gate  ->  summarize  ->  save
  ->  email one digest of everything new.

Unattended, so there is no per-run cost approval — `daily_budget_usd` is the
guard. A video is only summarized if its worst-case cost keeps today's UTC spend
at or under the cap; otherwise it is deferred and picked up on a later cycle
(after midnight UTC, spend resets). The monitor shares the single-job slot with
user-initiated jobs via JobRegistry, so the two never run concurrently.
"""

from __future__ import annotations

import html
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from yt_summarizer import notifications, transcripts, youtube_client
from yt_summarizer.claude_client import ClaudeSummarizer, SummarizerError
from yt_summarizer.config import Config
from yt_summarizer.database import Database
from yt_summarizer.youtube_client import Video, YouTubeRateLimitError

from .jobs import JobRegistry

log = logging.getLogger(__name__)


@dataclass
class _Summarized:
    channel_label: str
    video: Video
    text: str
    cost_usd: float | None


@dataclass
class CycleResult:
    skipped: bool = False  # another job was running; nothing done
    summarized: int = 0
    failed: int = 0
    budget_hit: bool = False
    spent_today: float = 0.0
    summaries: list[_Summarized] = field(default_factory=list)


def _utc_midnight_iso() -> str:
    """Start of the current UTC day, matching the format stored in processed_at."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


class ChannelMonitor:
    def __init__(
        self,
        config: Config,
        db: Database,
        summarizer: ClaudeSummarizer,
        jobs: JobRegistry,
    ) -> None:
        self._config = config
        self._db = db
        self._summarizer = summarizer
        self._jobs = jobs
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="channel-monitor", daemon=True)
        self._thread.start()
        log.info(
            "Channel monitor started — checking every %d min",
            self._config.monitor.interval_minutes,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("Channel monitor stopped")

    def trigger_async(self) -> None:
        """Run one cycle in a throwaway thread (used by POST /api/monitor/run)."""
        threading.Thread(target=self._safe_run_cycle, name="monitor-manual", daemon=True).start()

    def _loop(self) -> None:
        interval = max(60, self._config.monitor.interval_minutes * 60)
        # Run once at startup (catch up on anything posted while we were down),
        # then every interval until stopped.
        while True:
            self._safe_run_cycle()
            if self._stop.wait(interval):
                break

    def _safe_run_cycle(self) -> None:
        try:
            self.run_cycle()
        except Exception:
            log.exception("Monitor cycle crashed")

    # -- core --------------------------------------------------------------

    def run_cycle(self) -> CycleResult:
        if not self._jobs.reserve_for_monitor():
            log.info("Monitor: skipping cycle — a summarization job is already running")
            return CycleResult(skipped=True)
        try:
            return self._run_cycle_locked()
        finally:
            self._jobs.release_monitor()

    def _run_cycle_locked(self) -> CycleResult:
        cfg = self._config
        budget = cfg.monitor.daily_budget_usd
        spent = self._db.spend_since(_utc_midnight_iso())
        processed = self._db.processed_ids()

        result = CycleResult(spent_today=spent)

        for channel in self._db.list_channels():
            if result.budget_hit:
                break
            prompt_name = channel["prompt_name"] or cfg.active_prompt
            if prompt_name not in cfg.prompts:
                log.warning(
                    "Monitor: channel %r has unknown prompt %r — using active_prompt %r",
                    channel["label"], prompt_name, cfg.active_prompt,
                )
                prompt_name = cfg.active_prompt
            prompt_text = cfg.prompts[prompt_name]

            try:
                videos = youtube_client.list_recent_videos(
                    channel["input"], cfg.monitor.max_videos_check
                )
            except YouTubeRateLimitError:
                log.warning(
                    "Monitor: YouTube rate limited listing %r — skipping this channel",
                    channel["label"],
                )
                continue

            new_videos = [
                v for v in videos
                if v.video_id not in processed and self._within_age(v)
            ]

            for video in new_videos:
                # Fetch transcript (same building blocks as the estimate router).
                try:
                    video, info = youtube_client.fetch_video_details(video)
                    transcript = transcripts.fetch_transcript(
                        info, video.video_id, cfg.transcript_languages
                    )
                except YouTubeRateLimitError:
                    log.warning(
                        "Monitor: YouTube 429 fetching %s — stopping this channel this cycle",
                        video.video_id,
                    )
                    break
                except transcripts.TranscriptError as exc:
                    log.info("Monitor: no transcript for %s (%s) — skipping", video.video_id, exc)
                    continue

                # Budget pre-check at worst case (full max_output_tokens).
                est = self._summarizer.estimate(
                    prompt_text, transcript, cfg.estimated_output_tokens
                )
                worst = self._summarizer.cost(est.input_tokens, self._summarizer.max_output_tokens)
                if budget > 0 and worst is not None and spent + worst > budget:
                    log.info(
                        "Monitor: daily budget $%.2f reached (spent $%.4f) — "
                        "deferring remaining videos to a later cycle",
                        budget, spent,
                    )
                    result.budget_hit = True
                    break

                try:
                    summary = self._summarizer.summarize(prompt_text, transcript)
                except SummarizerError as exc:
                    log.error("Monitor: failed to summarize %s: %s", video.video_id, exc)
                    result.failed += 1
                    continue

                self._db.save_summary(
                    video_id=video.video_id,
                    title=video.title,
                    url=video.url,
                    published_at=video.published_at,
                    transcript=transcript,
                    prompt_name=prompt_name,
                    model=cfg.model,
                    ai_response=summary.text,
                    tokens_input=summary.tokens_input,
                    tokens_output=summary.tokens_output,
                    cost_usd=summary.cost_usd,
                    channel_id=channel["id"],
                )
                processed.add(video.video_id)
                spent += summary.cost_usd or 0.0
                result.summaries.append(
                    _Summarized(
                        channel_label=channel["label"],
                        video=video,
                        text=summary.text,
                        cost_usd=summary.cost_usd,
                    )
                )

        result.summarized = len(result.summaries)
        result.spent_today = spent

        if result.summaries:
            self._maybe_send_email(result, budget)

        log.info(
            "Monitor cycle done: %d summarized, %d failed, budget_hit=%s, spent $%.4f today",
            result.summarized, result.failed, result.budget_hit, spent,
        )
        return result

    # -- helpers -----------------------------------------------------------

    def _within_age(self, video: Video) -> bool:
        max_age = self._config.monitor.max_age_hours
        if max_age <= 0:
            return True
        if not video.published_at:
            # Unknown publish date — don't auto-process when an age limit is set.
            return False
        try:
            published = datetime.fromisoformat(video.published_at)
        except ValueError:
            return False
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published >= datetime.now(timezone.utc) - timedelta(hours=max_age)

    def _maybe_send_email(self, result: CycleResult, budget: float) -> None:
        mon = self._config.monitor
        api_key = os.getenv("RESEND_API_KEY", "")
        if not api_key or not mon.notify_emails:
            log.warning(
                "Monitor: %d new summaries but no email sent "
                "(set RESEND_API_KEY and monitoring.notify_emails)",
                result.summarized,
            )
            return
        subject = f"{mon.subject_prefix} ({result.summarized})"
        body = self._build_html(result, budget)
        try:
            notifications.send_email(
                api_key=api_key,
                sender=mon.resend_from,
                recipients=mon.notify_emails,
                subject=subject,
                html=body,
            )
        except notifications.NotificationError as exc:
            log.error("Monitor: could not send digest email: %s", exc)

    def _build_html(self, result: CycleResult, budget: float) -> str:
        blocks: list[str] = []
        for s in result.summaries:
            title = html.escape(s.video.title)
            url = html.escape(s.video.url, quote=True)
            channel = html.escape(s.channel_label)
            date = html.escape(s.video.published_at or "")
            cost = f"${s.cost_usd:.4f}" if s.cost_usd is not None else "n/a"
            text = html.escape(s.text).replace("\n", "<br>")
            blocks.append(
                f'<div style="margin-bottom:28px">'
                f'<div style="font-size:12px;color:#666">{channel} &middot; {date} &middot; {cost}</div>'
                f'<h2 style="margin:4px 0;font-size:18px">'
                f'<a href="{url}" style="color:#0b57d0;text-decoration:none">{title}</a></h2>'
                f'<div style="line-height:1.5;white-space:normal">{text}</div>'
                f"</div>"
            )
        footer = f'<p style="font-size:12px;color:#666">Spent today: ${result.spent_today:.4f}'
        if budget > 0:
            footer += f" / ${budget:.2f} budget"
        footer += "</p>"
        if result.budget_hit:
            footer += (
                '<p style="font-size:12px;color:#a00">&#9888; Daily budget reached — '
                "remaining new videos were deferred and will be processed after midnight UTC.</p>"
            )
        if result.failed:
            footer += (
                f'<p style="font-size:12px;color:#a00">{result.failed} video(s) '
                "failed to summarize — see server logs.</p>"
            )
        return (
            '<div style="font-family:system-ui,-apple-system,sans-serif;'
            'max-width:640px;margin:0 auto;color:#111">'
            + "".join(blocks)
            + "<hr>"
            + footer
            + "</div>"
        )
