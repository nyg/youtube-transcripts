"""Full-text search over stored transcripts and summaries (SQLite FTS5)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import SearchHitOut

router = APIRouter(prefix="/api/search")


@router.get("", response_model=list[SearchHitOut])
def search(
    request: Request,
    q: str = "",
    channel_id: int | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[SearchHitOut]:
    if not q.strip():
        return []
    rows = request.app.state.db.search(
        q, channel_id=channel_id, since=since, limit=min(limit, 200)
    )
    return [SearchHitOut.model_validate(dict(row)) for row in rows]
