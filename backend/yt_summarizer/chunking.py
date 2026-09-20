from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .transcripts import Segment

CHUNK_WINDOW_SECONDS = 60
CHUNK_WORDS = 200

_TOKEN = re.compile(r'"[^"]*"|\S+')
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Chunk:
    kind: str
    text: str
    start_seconds: int | None = None


def _from_segments(segments: Sequence[Segment]) -> list[Chunk]:
    chunks: list[Chunk] = []
    start: int | None = None
    parts: list[str] = []
    for segment in segments:
        at = segment.start_ms // 1000
        if start is None or at - start >= CHUNK_WINDOW_SECONDS:
            if parts and start is not None:
                chunks.append(Chunk("transcript", " ".join(parts), start))
            start = at
            parts = []
        parts.append(segment.text)
    if parts and start is not None:
        chunks.append(Chunk("transcript", " ".join(parts), start))
    return chunks


def _from_text(text: str) -> list[Chunk]:
    words = text.split()
    return [
        Chunk("transcript", " ".join(words[index : index + CHUNK_WORDS]))
        for index in range(0, len(words), CHUNK_WORDS)
    ]


def build_chunks(
    transcript: str, segments: Sequence[Segment] | None, summary: str
) -> list[Chunk]:
    chunks = _from_segments(segments) if segments else _from_text(transcript)
    if summary.strip():
        chunks.append(Chunk("summary", summary.strip()))
    return chunks


def fts_query(text: str) -> str | None:
    terms: list[str] = []
    for raw in _TOKEN.findall(text):
        if raw.startswith('"'):
            words = _WORD.findall(raw)
            if words:
                terms.append('"' + " ".join(words) + '"')
            continue
        words = _WORD.findall(raw)
        if words:
            terms.append('"' + " ".join(words) + '"')
    if not terms:
        return None
    if not text.rstrip().endswith('"'):
        terms[-1] += "*"
    return " ".join(terms)
