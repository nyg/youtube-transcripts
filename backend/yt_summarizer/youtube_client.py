"""Channel video listing via yt-dlp — no YouTube API key required.

The channel's /videos and /streams tabs are fetched with flat playlist
extraction (cheap, two requests total). Shorts live under the separate
/shorts tab and are therefore never included.
"""

from __future__ import annotations

import logging
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime, timezone
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
    # UTC ISO 8601 timestamp (e.g. "2026-07-18T18:00:38+00:00"); the frontend
    # renders it in the viewer's local timezone and locale.
    published_at: str | None
    url: str
    timestamp: int | None = None  # epoch seconds, used for sorting
    # True while the date is only the cheap approximation from the flat channel
    # listing (day-level, no time). Exact dates come from the RSS feed or a
    # per-video metadata fetch.
    date_is_approximate: bool = False


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


def _utc_iso(ts: float | None) -> str | None:
    """Epoch seconds → UTC ISO 8601, e.g. '2026-07-18T18:00:38+00:00'."""
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _list_tab(tab_url: str, max_videos: int) -> tuple[str | None, list[Video]]:
    """Return (channel_id, videos) for one channel tab via flat extraction."""
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
        return None, []

    info = info or {}
    videos: list[Video] = []
    for entry in info.get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        ts = entry.get("timestamp") or entry.get("release_timestamp")
        videos.append(
            Video(
                video_id=entry["id"],
                title=entry.get("title") or entry["id"],
                published_at=_utc_iso(ts),
                url=f"https://www.youtube.com/watch?v={entry['id']}",
                timestamp=int(ts) if ts else None,
                date_is_approximate=True,
            )
        )
    return info.get("channel_id"), videos


def _fetch_rss_dates(channel_id: str) -> dict[str, str]:
    """Exact publish dates for the ~15 newest videos, from the channel's RSS
    feed. One cheap request, no per-video metadata extraction. Returns a
    video_id → UTC ISO 8601 mapping (empty on any failure)."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        raw = fetch_url(url)
    except Exception as exc:  # network / 429 / parse — dates stay approximate
        log.debug("RSS date fetch failed for %s: %s", channel_id, exc)
        return {}
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    dates: dict[str, str] = {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        log.debug("Could not parse RSS feed for %s: %s", channel_id, exc)
        return {}
    for entry in root.findall("atom:entry", ns):
        video_id = entry.findtext("yt:videoId", namespaces=ns)
        published = entry.findtext("atom:published", namespaces=ns)
        if video_id and published:
            dates[video_id] = published
    return dates


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


def _to_epoch(iso: str) -> int | None:
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return None


def list_recent_videos(channel: str, max_videos: int) -> list[Video]:
    """Return the channel's most recent videos + live VODs, newest first.

    Dates from the flat listing are only approximate; they are upgraded to the
    exact publish times from the channel's RSS feed (one cheap request covering
    the ~15 newest videos) where available.
    """
    base = _normalize_channel_url(channel)
    merged: dict[str, Video] = {}
    channel_id: str | None = None
    for tab in _TABS:
        tab_channel_id, videos = _list_tab(f"{base}/{tab}", max_videos)
        channel_id = channel_id or tab_channel_id
        for video in videos:
            merged.setdefault(video.video_id, video)

    if channel_id:
        for video_id, published in _fetch_rss_dates(channel_id).items():
            existing = merged.get(video_id)
            if existing is not None:
                merged[video_id] = replace(
                    existing,
                    published_at=published,
                    timestamp=_to_epoch(published) or existing.timestamp,
                    date_is_approximate=False,
                )

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
        published = _utc_iso(ts)
        approximate = False
    elif upload_date:
        # Only a date is known (no time of day) — treat it as UTC midnight.
        published = (
            datetime.strptime(str(upload_date), "%Y%m%d")
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
        approximate = False
    else:
        published = video.published_at
        approximate = video.date_is_approximate

    video = replace(
        video,
        title=info.get("title") or video.title,
        published_at=published,
        timestamp=int(ts) if ts else video.timestamp,
        date_is_approximate=approximate,
    )
    return video, info
