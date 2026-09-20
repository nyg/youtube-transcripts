from __future__ import annotations

import json
import sqlite3

from yt_summarizer.claude_client import Extraction
from yt_summarizer.database import Database


def stance_labels(prompt: sqlite3.Row) -> list[str]:
    raw = prompt["stance_labels"] if "stance_labels" in prompt.keys() else None
    if not raw:
        return []
    try:
        labels = json.loads(raw)
    except ValueError:
        return []
    return [str(label) for label in labels if str(label).strip()]


def extraction_for(db: Database, prompt: sqlite3.Row) -> Extraction | None:
    labels = stance_labels(prompt)
    if not labels:
        return None
    entity_kind = (prompt["entity_kind"] or "").strip() or "topic"
    return Extraction(
        entity_kind=entity_kind,
        stance_labels=labels,
        known_entities=db.known_entities(prompt["name"]),
    )
