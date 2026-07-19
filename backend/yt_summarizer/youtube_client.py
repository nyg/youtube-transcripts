"""Channel video listing via yt-dlp — no YouTube API key required.

The channel's /videos and /streams tabs are fetched with flat playlist
extraction (cheap, two requests total). Shorts live under the separate
/shorts tab and are therefore never included.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import DownloadError

log = logging.getLogger(__name__)

_TABS = ("videos", "streams")


class YouTubeRateLimitError(Exception):
    """Raised when YouTube answers HTTP 429 (IP is being rate limited)."""


# Set once at startup via configure(); pacing applies process-wide so that
# concurrent requests cannot hammer YouTube in parallel.
_request_interval = 0.0
_cookiefile: Path | None = None
_throttle_lock = threading.Lock()
_last_request = 0.0


def configure(*, request_interval: float, cookiefile: Path | None) -> None:
    global _request_interval, _cookiefile
    _request_interval = request_interval
    _cookiefile = cookiefile


def _throttle() -> None:
    """Block until at least `_request_interval` has passed since the last
    YouTube request. Sleeping under the lock serializes concurrent callers."""
    global _last_request
    with _throttle_lock:
        wait = _request_interval - (time.monotonic() - _last_request)
        if wait > 0:
            log.info("Throttling YouTube request for %.1fs", wait)
            time.sleep(wait)
        _last_request = time.monotonic()


def _ydl_opts(**extra: Any) -> Any:
    # Typed as Any because yt-dlp's params stub rejects plain dicts.
    opts: dict[str, Any] = {"quiet": True, "no_warnings": True}
    if _cookiefile is not None:
        opts["cookiefile"] = str(_cookiefile)
    opts.update(extra)
    return opts


def _is_rate_limit(exc: Exception) -> bool:
    return "HTTP Error 429" in str(exc) or "Too Many Requests" in str(exc)


def fetch_url(url: str) -> bytes:
    """Throttled download of one URL through yt-dlp's HTTP stack (UA,
    cookies). Raises YouTubeRateLimitError on 429; other request errors
    propagate as yt_dlp.networking.exceptions.RequestError."""
    _throttle()
    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        try:
            return ydl.urlopen(url).read()
        except HTTPError as exc:
            if exc.status == 429:
                raise YouTubeRateLimitError(
                    "YouTube rate limit (HTTP 429) — wait a few minutes and retry."
                ) from exc
            raise


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    published_at: str | None  # local "YYYY-MM-DD HH:MM[:SS]"; approximate at listing time
    url: str
    timestamp: int | None = None  # epoch seconds, used for sorting


def _normalize_channel_url(channel: str) -> str:
    """Accept an @handle, a UC... channel ID, or a full URL."""
    channel = channel.strip().rstrip("/")
    if not channel:
        raise ValueError("No channel provided — expected an @handle, a UC... channel ID, or a URL")
    if channel.startswith(("http://", "https://")):
        base = channel
    elif channel.startswith("@"):
        base = f"https://www.youtube.com/{channel}"
    elif channel.startswith("UC"):
        base = f"https://www.youtube.com/channel/{channel}"
    else:
        base = f"https://www.youtube.com/@{channel}"
    for tab in ("/videos", "/streams", "/shorts", "/featured"):
        if base.endswith(tab):
            base = base[: -len(tab)]
    return base


def _local_datetime(ts: float | None) -> str | None:
    """Epoch seconds → local 'YYYY-MM-DD HH:MM'."""
    if not ts:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _list_tab(tab_url: str, max_videos: int) -> list[Video]:
    opts = _ydl_opts(
        extract_flat="in_playlist",
        playlist_items=f"1:{max_videos}",
        # Gives flat entries an approximate `timestamp`, so the two tabs can
        # be merged and sorted without one metadata request per video.
        extractor_args={"youtubetab": {"approximate_date": [""]}},
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(tab_url, download=False)
    except DownloadError as exc:
        # Channels without lives (or without uploads) simply lack the tab.
        log.debug("No entries for %s: %s", tab_url, exc)
        return []

    videos: list[Video] = []
    for entry in (info or {}).get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        ts = entry.get("timestamp") or entry.get("release_timestamp")
        videos.append(
            Video(
                video_id=entry["id"],
                title=entry.get("title") or entry["id"],
                published_at=_local_datetime(ts),
                url=f"https://www.youtube.com/watch?v={entry['id']}",
                timestamp=int(ts) if ts else None,
            )
        )
    return videos


def probe_channel(channel: str) -> str | None:
    """Cheaply verify that a channel exists and return its display name.

    Returns None when the channel cannot be resolved. Raises ValueError for
    syntactically invalid input (empty string).
    """
    base = _normalize_channel_url(channel)
    opts = _ydl_opts(extract_flat="in_playlist", playlist_items="1:1")
    for tab in _TABS:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"{base}/{tab}", download=False) or {}
        except DownloadError as exc:
            log.debug("Probe failed for %s/%s: %s", base, tab, exc)
            continue
        return info.get("channel") or info.get("uploader") or channel
    return None


def list_recent_videos(channel: str, max_videos: int) -> list[Video]:
    """Return the channel's most recent videos + live VODs, newest first."""
    base = _normalize_channel_url(channel)
    merged: dict[str, Video] = {}
    for tab in _TABS:
        for video in _list_tab(f"{base}/{tab}", max_videos):
            merged.setdefault(video.video_id, video)
    ordered = sorted(merged.values(), key=lambda v: v.timestamp or 0, reverse=True)
    return ordered[:max_videos]


def fetch_video_details(video: Video) -> tuple[Video, dict[str, Any] | None]:
    """Fetch full metadata for one video to get its exact publish date/title.

    Also returns the raw info dict (None if extraction failed) so callers can
    reuse the caption track URLs it contains instead of extracting the video
    a second time. Only called for videos actually selected for processing —
    the flat listing carries approximate dates only.

    Raises YouTubeRateLimitError when YouTube answers 429.
    """
    _throttle()
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(skip_download=True)) as ydl:
            info: dict[str, Any] = dict(ydl.extract_info(video.url, download=False) or {})
    except DownloadError as exc:
        if _is_rate_limit(exc):
            raise YouTubeRateLimitError(
                "YouTube rate limit (HTTP 429) — wait a few minutes and retry."
            ) from exc
        log.warning("Could not fetch full metadata for %s: %s", video.video_id, exc)
        return video, None

    ts = info.get("release_timestamp") or info.get("timestamp")
    upload_date = info.get("upload_date")
    if ts:
        published = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    elif upload_date:
        published = datetime.strptime(str(upload_date), "%Y%m%d").date().isoformat()
    else:
        published = video.published_at

    video = replace(
        video,
        title=info.get("title") or video.title,
        published_at=published,
        timestamp=int(ts) if ts else video.timestamp,
    )
    return video, info
