"""Background monitor: scheduled checks for new videos, auto-summarize, email digest.

Runs inside the FastAPI process as a daemon thread (started/stopped in the app
lifespan). The thread idles while monitoring is disabled and follows the settings
as they are edited. Cycles fire on the `monitoring.schedule` cron expression,
evaluated in the server's local time, so the timing is wall-clock stable and
independent of when the process was started. One "cycle" per fire:

  discover new videos per channel  ->  budget-gate  ->  summarize  ->  save
  ->  email one digest per channel to that channel's recipients.

Unattended, so there is no per-run cost approval — `daily_budget_usd` is the
guard. A video is only summarized if its worst-case cost keeps today's UTC spend
at or under the cap; otherwise it is deferred and picked up on a later cycle
(after midnight UTC, spend resets). The monitor shares the single-job slot with
user-initiated jobs via JobRegistry, so the two never run concurrently.

Note the deliberate split: schedules fire in local time (an operator asking for
08:00 means their 08:00), while every timestamp stored or served stays UTC.
"""

from __future__ import annotations

import html
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from croniter import croniter

from yt_summarizer import markdown_email, notifications, transcripts, youtube_client
from yt_summarizer.claude_client import ClaudeSummarizer, SummarizerError
from yt_summarizer.database import Database
from yt_summarizer.models import ModelCatalog
from yt_summarizer.transcripts import segments_to_json
from yt_summarizer.youtube_client import Video, YouTubeRateLimitError

from .jobs import JobRegistry
from .prompts import extraction_for, settings_for
from .settings import SettingsStore

log = logging.getLogger(__name__)

# Mail clients truncate long subjects anyway; keep the video title from running away.
_MAX_SUBJECT_TITLE = 90


@dataclass
class _Summarized:
    channel_id: int | None
    channel_label: str
    recipients: list[str]
    video: Video
    text: str
    cost_usd: float


@dataclass
class CycleResult:
    skipped: bool = False  # another job was running; nothing done
    summarized: int = 0
    failed: int = 0
    budget_hit: bool = False
    spent_today: float = 0.0
    summaries: list[_Summarized] = field(default_factory=list)


def _local_now() -> datetime:
    """Timezone-aware 'now' in the server's local zone, for cron arithmetic."""
    return datetime.now().astimezone()


def _utc_midnight_iso() -> str:
    """Start of the current UTC day, matching the format stored in processed_at."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def _email_date(iso: str) -> str:
    """Format a stored UTC timestamp for the digest.

    The one place we format a date server-side: an email has no client to render
    it in the reader's locale, and a bare ISO string reads terribly in an inbox.
    """
    if not iso:
        return ""
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


class ChannelMonitor:
    def __init__(
        self,
        settings: SettingsStore,
        db: Database,
        summarizer: ClaudeSummarizer,
        jobs: JobRegistry,
        catalog: ModelCatalog,
    ) -> None:
        self._settings = settings
        self._db = db
        self._summarizer = summarizer
        self._jobs = jobs
        self._catalog = catalog
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def next_run_at(self) -> datetime | None:
        """When the next scheduled cycle fires; None while not running or disabled."""
        running = self._thread is not None and self._thread.is_alive()
        if not running or not self._settings.current.monitor.enabled:
            return None
        return self._next_run(_local_now())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, name="channel-monitor", daemon=True)
        self._thread.start()
        self._log_schedule()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("Channel monitor stopped")

    def refresh(self) -> None:
        """Pick up edited settings: wakes the loop so it re-reads the schedule."""
        self._wake.set()
        self._log_schedule()

    def _log_schedule(self) -> None:
        monitor = self._settings.current.monitor
        if not monitor.enabled:
            log.info("Channel monitor idle (enable monitoring in Settings)")
            return
        log.info(
            "Channel monitor on — schedule %r (local time), next run %s",
            monitor.schedule,
            self._next_run(_local_now()).strftime("%Y-%m-%d %H:%M %Z"),
        )

    def trigger_async(self) -> None:
        """Run one cycle in a throwaway thread (used by POST /api/monitor/run)."""
        threading.Thread(target=self._safe_run_cycle, name="monitor-manual", daemon=True).start()

    def _next_run(self, after: datetime) -> datetime:
        """The first scheduled fire time strictly after `after`."""
        return croniter(self._settings.current.monitor.schedule, after).get_next(datetime)

    def _loop(self) -> None:
        # Optionally catch up on anything posted while we were down, then follow
        # the cron schedule. The next fire time is recomputed every iteration
        # rather than accumulated, so a slow cycle doesn't push the schedule
        # forward and a DST shift resolves itself.
        monitor = self._settings.current.monitor
        if monitor.enabled and monitor.run_on_start:
            self._safe_run_cycle()
        while not self._stop.is_set():
            delay = None
            if self._settings.current.monitor.enabled:
                now = _local_now()
                delay = max(1.0, (self._next_run(now) - now).total_seconds())
            # Woken by stop() or refresh(): re-read the settings instead of running.
            if self._wake.wait(delay):
                self._wake.clear()
                continue
            self._safe_run_cycle()

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
        cfg = self._settings.current
        budget = cfg.monitor.daily_budget_usd
        spent = self._db.spend_since(_utc_midnight_iso())
        processed = self._db.processed_ids()

        result = CycleResult(spent_today=spent)

        for channel in self._db.list_channels():
            if result.budget_hit:
                break
            prompt_row = (
                self._db.get_prompt_by_name(channel["prompt_name"])
                if channel["prompt_name"]
                else None
            )
            if prompt_row is None:
                log.warning(
                    "Monitor: channel %r has no valid prompt (%r) — skipping",
                    channel["label"], channel["prompt_name"],
                )
                continue
            prompt_name = prompt_row["name"]
            settings = settings_for(prompt_row, self._catalog, cfg.pricing)
            if settings is None:
                log.warning(
                    "Monitor: prompt %r of channel %r has no model or effort — skipping",
                    prompt_name, channel["label"],
                )
                continue
            prompt_text = prompt_row["text"]
            prompt_output_tokens = prompt_row["estimated_output_tokens"]
            extraction = extraction_for(self._db, prompt_row)
            recipients = json.loads(channel["notify_emails"] or "[]")

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
                    settings, prompt_text, transcript, prompt_output_tokens, extraction
                )
                worst = self._summarizer.cost(
                    settings, est.input_tokens, settings.max_output_tokens
                )
                if budget > 0 and spent + worst > budget:
                    log.info(
                        "Monitor: daily budget $%.2f reached (spent $%.4f) — "
                        "deferring remaining videos to a later cycle",
                        budget, spent,
                    )
                    result.budget_hit = True
                    break

                try:
                    summary = self._summarizer.summarize(
                        settings, prompt_text, transcript, extraction
                    )
                except SummarizerError as exc:
                    log.error("Monitor: failed to summarize %s: %s", video.video_id, exc)
                    result.failed += 1
                    continue

                self._db.save_summary(
                    video_id=video.video_id,
                    title=video.title,
                    url=video.url,
                    published_at=video.published_at,
                    transcript=transcript.text,
                    transcript_segments=segments_to_json(transcript.segments),
                    transcript_source=transcript.source,
                    mentions=summary.mentions,
                    prompt_name=prompt_name,
                    model=settings.model,
                    ai_response=summary.text,
                    tokens_input=summary.tokens_input,
                    tokens_output=summary.tokens_output,
                    cost_usd=summary.cost_usd,
                    channel_id=channel["id"],
                    effort=settings.effort,
                    max_output_tokens=settings.max_output_tokens,
                    estimated_output_tokens=prompt_output_tokens,
                    tokens_thinking=summary.tokens_thinking,
                    stop_reason=summary.stop_reason,
                    duration_ms=summary.duration_ms,
                )
                processed.add(video.video_id)
                spent += summary.cost_usd
                result.summaries.append(
                    _Summarized(
                        channel_id=channel["id"],
                        channel_label=channel["label"],
                        recipients=recipients,
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
        max_age = self._settings.current.monitor.max_age_hours
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
        mon = self._settings.current.monitor
        api_key = os.getenv("RESEND_API_KEY", "")
        if not api_key:
            log.warning(
                "Monitor: %d new summaries but RESEND_API_KEY is not set — no email sent",
                result.summarized,
            )
            return

        # One digest per channel, sent to that channel's own recipients.
        by_channel: dict[int | None, list[_Summarized]] = {}
        for s in result.summaries:
            by_channel.setdefault(s.channel_id, []).append(s)

        for summaries in by_channel.values():
            label = summaries[0].channel_label
            recipients = summaries[0].recipients
            if not recipients:
                log.info(
                    "Monitor: %d new summaries for %r but no recipients configured — not emailing",
                    len(summaries), label,
                )
                continue
            subject = self._build_subject(label, summaries)
            body = self._build_html(summaries, result, budget)
            try:
                notifications.send_email(
                    api_key=api_key,
                    sender=mon.resend_from,
                    recipients=recipients,
                    subject=subject,
                    html=body,
                )
            except notifications.NotificationError as exc:
                log.error("Monitor: could not send digest email for %r: %s", label, exc)

    def _build_subject(self, label: str, summaries: list[_Summarized]) -> str:
        """One video → name it in the subject; several → fall back to a count."""
        prefix = self._settings.current.monitor.subject_prefix
        if len(summaries) != 1:
            return f"{prefix} — {label} ({len(summaries)})"
        # Collapse whitespace: a newline here would be a mail-header break.
        title = " ".join(summaries[0].video.title.split())
        if len(title) > _MAX_SUBJECT_TITLE:
            title = title[: _MAX_SUBJECT_TITLE - 1].rstrip() + "…"
        return f"{prefix} — {label}: {title}"

    def _build_html(
        self, summaries: list[_Summarized], result: CycleResult, budget: float
    ) -> str:
        blocks: list[str] = []
        for s in summaries:
            title = html.escape(s.video.title)
            url = html.escape(s.video.url, quote=True)
            channel = html.escape(s.channel_label)
            date = html.escape(_email_date(s.video.published_at or ""))
            cost = f"${s.cost_usd:.4f}"
            text = markdown_email.render(s.text)
            blocks.append(
                f'<div style="margin-bottom:28px">'
                f'<div style="font-size:12px;color:#666">{channel} &middot; {date} &middot; {cost}</div>'
                f'<h2 style="margin:4px 0 10px;font-size:18px">'
                f'<a href="{url}" style="color:#0b57d0;text-decoration:none">{title}</a></h2>'
                f'<div style="line-height:1.5">{text}</div>'
                f"</div>"
            )
        footer = f'<p style="font-size:12px;color:#666">Spent today: ${result.spent_today:.4f}'
        if budget > 0:
            footer += f" / ${budget:.2f} budget"
        footer += "</p>"
        if result.budget_hit:
            footer += (
                '<p style="font-size:12px;color:#a00">&#9888; Daily budget reached. '
                "The remaining videos will be summarized after midnight UTC.</p>"
            )
        if result.failed:
            footer += (
                f'<p style="font-size:12px;color:#a00">{result.failed} video(s) '
                "could not be summarized. See the server logs.</p>"
            )
        return (
            '<div style="font-family:system-ui,-apple-system,sans-serif;'
            'max-width:640px;margin:0 auto;color:#111">'
            + "".join(blocks)
            + "<hr>"
            + footer
            + "</div>"
        )
