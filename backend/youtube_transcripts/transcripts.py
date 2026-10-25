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
from dataclasses import dataclass, replace
from typing import Any, Literal

from yt_dlp.networking.exceptions import RequestError

from . import youtube_client
from .youtube_client import YouTubeRateLimitError

log = logging.getLogger(__name__)

_RATE_LIMIT_BACKOFF_SECONDS = 20.0
_TIMESTAMP_WINDOW_SECONDS = 30


TranscriptSource = Literal["manual", "auto"]


class TranscriptError(Exception):
    """Raised when no transcript could be retrieved for a video."""


@dataclass(frozen=True)
class CaptionTrack:
    url: str
    source: TranscriptSource


@dataclass(frozen=True)
class Segment:
    start_ms: int
    text: str


@dataclass(frozen=True)
class Transcript:
    text: str
    segments: list[Segment] | None = None
    source: TranscriptSource | None = None

    def rendered(self, *, timestamps: bool) -> str:
        if timestamps and self.segments:
            return render_timestamped(self.segments)
        return self.text


def _stamp(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def render_timestamped(
    segments: Sequence[Segment], window_seconds: int = _TIMESTAMP_WINDOW_SECONDS
) -> str:
    lines: list[str] = []
    start: int | None = None
    parts: list[str] = []
    for segment in segments:
        at = segment.start_ms // 1000
        if start is None or at - start >= window_seconds:
            if parts and start is not None:
                lines.append(f"[{_stamp(start)}] {' '.join(parts)}")
            start = at
            parts = []
        parts.append(segment.text)
    if parts and start is not None:
        lines.append(f"[{_stamp(start)}] {' '.join(parts)}")
    return "\n".join(lines)


def segments_to_json(segments: Sequence[Segment] | None) -> str | None:
    if not segments:
        return None
    return json.dumps([[s.start_ms, s.text] for s in segments], ensure_ascii=False)


def segments_from_json(raw: str | None) -> list[Segment] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    segments = [
        Segment(start_ms=int(item[0]), text=str(item[1]))
        for item in data
        if isinstance(item, list) and len(item) == 2
    ]
    return segments or None


def _parse_json3(raw: str) -> Transcript:
    events = (json.loads(raw).get("events") or []) if raw else []
    segments: list[Segment] = []
    for event in events:
        parts: list[str] = []
        for seg in event.get("segs") or []:
            text = seg.get("utf8", "").replace("\n", " ").strip()
            if text:
                parts.append(text)
        joined = " ".join(" ".join(parts).split())
        if joined:
            segments.append(Segment(start_ms=int(event.get("tStartMs") or 0), text=joined))
    return Transcript(
        text=" ".join(segment.text for segment in segments),
        segments=segments or None,
    )


def select_caption_track(info: dict[str, Any], languages: Sequence[str]) -> CaptionTrack | None:
    """Return the single best caption track (its json3 URL and source), or None.

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
        if url := match_language(manual, lang):
            return CaptionTrack(url, "manual")
        if url := match_language(auto, lang):
            return CaptionTrack(url, "auto")
    for key in auto:
        if key.endswith("-orig") and (url := json3_url(auto, key)):
            return CaptionTrack(url, "auto")
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
            raise TranscriptError(f"Could not download the transcript: {exc}") from exc
    raise AssertionError("unreachable")


def fetch_transcript(
    info: dict[str, Any] | None, video_id: str, languages: Sequence[str]
) -> Transcript:
    """Return the full transcript, preferring `languages` in order.

    `info` is the dict from youtube_client.fetch_video_details (None if that
    extraction failed). Videos without captions are detected from the info
    dict alone — no extra request is made for them.

    Raises TranscriptError when no transcript exists, YouTubeRateLimitError
    when YouTube keeps answering 429 after a backoff retry.
    """
    if not info:
        raise TranscriptError("Could not load the video details.")

    track = select_caption_track(info, languages)
    if track is None:
        raise TranscriptError("This video has no transcript.")

    transcript = _parse_json3(_download_caption(track.url, video_id))
    if not transcript.text:
        raise TranscriptError("The transcript is empty.")
    return replace(transcript, source=track.source)
