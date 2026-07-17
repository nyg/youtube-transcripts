"""Transcript fetching via youtube-transcript-api."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    YouTubeTranscriptApi,
)

log = logging.getLogger(__name__)


class TranscriptError(Exception):
    """Raised when no transcript could be retrieved for a video."""


def _join(fetched) -> str:
    parts = []
    for snippet in fetched:
        text = snippet.text.replace("\n", " ").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def fetch_transcript(video_id: str, languages: Sequence[str]) -> str:
    """Return the full transcript text, preferring `languages` in order.

    Falls back to any available transcript (including auto-generated ones in
    other languages) before giving up.
    """
    api = YouTubeTranscriptApi()
    try:
        try:
            return _join(api.fetch(video_id, languages=list(languages)))
        except NoTranscriptFound:
            log.debug("No transcript in %s for %s, falling back to any language", languages, video_id)
            for transcript in api.list(video_id):
                return _join(transcript.fetch())
            raise TranscriptError(f"No transcript available for video {video_id}") from None
    except CouldNotRetrieveTranscript as exc:
        raise TranscriptError(f"Could not retrieve transcript for {video_id}: {exc.__class__.__name__}") from exc
