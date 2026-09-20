"""Structured mentions extracted from transcripts: per-entity overview and timeline."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import EntityOut, MentionOut

router = APIRouter(prefix="/api")


@router.get("/entities", response_model=list[EntityOut])
def list_entities(
    request: Request, channel_id: int | None = None, since: str | None = None
) -> list[EntityOut]:
    rows = request.app.state.db.entity_overview(channel_id=channel_id, since=since)
    return [EntityOut.model_validate(row) for row in rows]


@router.get("/mentions", response_model=list[MentionOut])
def list_mentions(
    request: Request,
    channel_id: int | None = None,
    entity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 500,
) -> list[MentionOut]:
    rows = request.app.state.db.list_mentions(
        channel_id=channel_id,
        entity=entity,
        since=since,
        until=until,
        limit=min(limit, 2000),
    )
    return [MentionOut.model_validate(dict(row)) for row in rows]
