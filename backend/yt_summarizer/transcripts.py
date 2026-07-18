"""Transcript fetching via yt-dlp caption download.

yt-dlp is used instead of youtube-transcript-api because YouTube blocks the
plain timedtext endpoint far more aggressively; yt-dlp's subtitle path goes
through its regular client handling (tokens, retries, client impersonation).
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

log = logging.getLogger(__name__)


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


def _language_preferences(languages: Sequence[str]) -> list[str]:
    """yt-dlp language selectors: preferred languages (with regional variants)
    first, plus the original-language auto track as a fallback — not "all",
    which would download every auto-translated language."""
    prefs: list[str] = []
    for lang in languages:
        prefs.extend((lang, f"{lang}-.*"))
    prefs.append(".*-orig")
    return prefs


def fetch_transcript(video_id: str, languages: Sequence[str]) -> str:
    """Return the full transcript text, preferring `languages` in order.

    Falls back to any available subtitle track (including auto-generated ones
    in other languages) before giving up. Manual subtitles win over automatic
    captions for the same language; that ordering is yt-dlp's default.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="yt-captions-") as tmpdir:
        opts: Any = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": _language_preferences(languages),
            "subtitlesformat": "json3",
            "outtmpl": {"default": f"{tmpdir}/%(id)s.%(ext)s"},
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except DownloadError as exc:
            raise TranscriptError(f"Could not retrieve transcript for {video_id}: {exc}") from exc

        files = sorted(Path(tmpdir).glob("*.json3"))
        if not files:
            raise TranscriptError(f"No transcript available for video {video_id}")

        # yt-dlp downloads tracks in preference order; files sort as
        # {id}.{lang}.json3, so pick the preferred language explicitly.
        chosen = files[0]
        for lang in languages:
            match = next((f for f in files if f.suffixes[0].lstrip(".").startswith(lang)), None)
            if match is not None:
                chosen = match
                break

        text = _parse_json3(chosen.read_text(encoding="utf-8"))
        if not text:
            raise TranscriptError(f"Transcript for video {video_id} is empty")
        return text
