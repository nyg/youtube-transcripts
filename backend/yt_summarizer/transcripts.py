"""Transcript fetching via yt-dlp caption download.

yt-dlp is used instead of youtube-transcript-api because YouTube blocks the
plain timedtext endpoint far more aggressively; yt-dlp's subtitle path goes
through its regular client handling (tokens, client impersonation).

YouTube rate-limits caption downloads per IP, so requests are kept to a
minimum: the caption track URLs are taken from the info dict of the metadata
extraction the caller already performed, and exactly one track is downloaded
per video (throttled, with a single backoff retry on HTTP 429).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from typing import Any

from yt_dlp.networking.exceptions import RequestError

from . import youtube_client
from .youtube_client import YouTubeRateLimitError

log = logging.getLogger(__name__)

_RATE_LIMIT_BACKOFF_SECONDS = 20.0


class TranscriptError(Exception):
    """Raised when no transcript could be retrieved for a video."""


def _parse_json3(raw: str) -> str:
    """Flatten a YouTube json3 caption file into one whitespace-joined string."""
    events = (json.loads(raw).get("events") or []) if raw else []
    parts: list[str] = []
    for event in events:
        for seg in event.get("segs") or []:
            text = seg.get("utf8", "").replace("\n", " ").strip()
            if text:
                parts.append(text)
    return " ".join(" ".join(parts).split())


def select_caption_track(info: dict[str, Any], languages: Sequence[str]) -> str | None:
    """Return the json3 URL of the single best caption track, or None.

    For each preferred language in order: manual subtitles (exact key, then a
    regional variant like "en-GB") win over automatic captions. Last resort is
    the original-language auto track ("xx-orig"), whatever its language.
    """
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    def json3_url(tracks: dict[str, Any], lang_key: str) -> str | None:
        for fmt in tracks.get(lang_key) or []:
            if fmt.get("ext") == "json3" and fmt.get("url"):
                return fmt["url"]
        return None

    def match_language(tracks: dict[str, Any], lang: str) -> str | None:
        if url := json3_url(tracks, lang):
            return url
        for key in tracks:
            if key.startswith(f"{lang}-") and (url := json3_url(tracks, key)):
                return url
        return None

    for lang in languages:
        for tracks in (manual, auto):
            if url := match_language(tracks, lang):
                return url
    for key in auto:
        if key.endswith("-orig") and (url := json3_url(auto, key)):
            return url
    return None


def _download_caption(url: str, video_id: str) -> str:
    for attempt in (1, 2):
        try:
            return youtube_client.fetch_url(url).decode("utf-8")
        except YouTubeRateLimitError:
            if attempt == 2:
                raise
            log.warning(
                "Rate limited downloading captions for %s; retrying in %.0fs",
                video_id,
                _RATE_LIMIT_BACKOFF_SECONDS,
            )
            time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
        except RequestError as exc:
            raise TranscriptError(
                f"Could not retrieve transcript for {video_id}: {exc}"
            ) from exc
    raise AssertionError("unreachable")


def fetch_transcript(
    info: dict[str, Any] | None, video_id: str, languages: Sequence[str]
) -> str:
    """Return the full transcript text, preferring `languages` in order.

    `info` is the dict from youtube_client.fetch_video_details (None if that
    extraction failed). Videos without captions are detected from the info
    dict alone — no extra request is made for them.

    Raises TranscriptError when no transcript exists, YouTubeRateLimitError
    when YouTube keeps answering 429 after a backoff retry.
    """
    if not info:
        raise TranscriptError(f"Could not retrieve video info for {video_id}")

    url = select_caption_track(info, languages)
    if url is None:
        raise TranscriptError(f"No transcript available for video {video_id}")

    text = _parse_json3(_download_caption(url, video_id))
    if not text:
        raise TranscriptError(f"Transcript for video {video_id} is empty")
    return text
