from __future__ import annotations

from dataclasses import dataclass

CONFIDENCE_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class Mention:
    entity: str
    stance: str
    confidence: str
    rationale: str
    quote: str
    timestamp_seconds: int | None = None


def entity_key(entity: str) -> str:
    return " ".join(entity.split()).casefold()
