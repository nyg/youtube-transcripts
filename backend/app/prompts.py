from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from yt_summarizer.claude_client import Extraction, ModelSettings
from yt_summarizer.config import ModelPricing
from yt_summarizer.database import Database
from yt_summarizer.models import ModelCatalog


def stance_labels(prompt: sqlite3.Row) -> list[str]:
    raw = prompt["stance_labels"] if "stance_labels" in prompt.keys() else None
    if not raw:
        return []
    try:
        labels = json.loads(raw)
    except ValueError:
        return []
    return [str(label) for label in labels if str(label).strip()]


def model_settings(
    catalog: ModelCatalog,
    pricing: Mapping[str, ModelPricing],
    family: str | None,
    effort: str | None,
    max_output_tokens: int,
) -> ModelSettings | None:
    model = catalog.resolve(family) if family else None
    if model is None:
        return None
    if not model.efforts:
        effort = None
    elif effort not in model.efforts:
        return None
    return ModelSettings(model.id, effort, max_output_tokens, pricing[model.family])


def settings_for(
    prompt: sqlite3.Row, catalog: ModelCatalog, pricing: Mapping[str, ModelPricing]
) -> ModelSettings | None:
    return model_settings(
        catalog, pricing, prompt["model"], prompt["effort"], prompt["max_output_tokens"]
    )


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
