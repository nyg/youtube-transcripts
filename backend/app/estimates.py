"""In-memory store carrying estimate results over to job creation.

An approved job must bill exactly what the user saw in the estimate, so the
transcripts fetched at estimate time are kept here and consumed (popped) when
the job is created. A missing entry means the estimate expired (server
restart, pruning) or was already used — the client re-runs the estimate.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from yt_summarizer.claude_client import CostEstimate
from yt_summarizer.youtube_client import Video

_MAX_ENTRIES = 20


@dataclass(frozen=True)
class PreparedVideo:
    video: Video
    transcript: str
    estimate: CostEstimate


@dataclass(frozen=True)
class PreparedEstimate:
    estimate_id: str
    channel_id: int
    prompt_name: str
    prompt_text: str
    items: dict[str, PreparedVideo]  # keyed by video_id, insertion-ordered


class EstimateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, PreparedEstimate] = {}

    def put(
        self,
        *,
        channel_id: int,
        prompt_name: str,
        prompt_text: str,
        items: dict[str, PreparedVideo],
    ) -> str:
        estimate_id = uuid.uuid4().hex
        entry = PreparedEstimate(estimate_id, channel_id, prompt_name, prompt_text, items)
        with self._lock:
            self._entries[estimate_id] = entry
            while len(self._entries) > _MAX_ENTRIES:
                self._entries.pop(next(iter(self._entries)))
        return estimate_id

    def pop(self, estimate_id: str) -> PreparedEstimate | None:
        with self._lock:
            return self._entries.pop(estimate_id, None)

    def restore(self, entry: PreparedEstimate) -> None:
        """Put back an entry popped by a job creation that was refused."""
        with self._lock:
            self._entries[entry.estimate_id] = entry
