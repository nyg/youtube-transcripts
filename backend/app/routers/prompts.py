"""Prompt management — the summarization templates channels choose from.

Prompts used to live in config.yaml; they are now a DB/UI-managed entity, each
carrying its own model family, effort, `max_output_tokens` and
`estimated_output_tokens`. A channel references a prompt by name, so a prompt
cannot be deleted while a channel still uses it.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request

from yt_summarizer.models import FAMILIES, ClaudeModel

from ..prompts import stance_labels
from ..schemas import MAX_STANCE_LABELS, PromptIn, PromptOut, PromptPatch

router = APIRouter(prefix="/api/prompts")


def _to_prompt(row: sqlite3.Row) -> PromptOut:
    return PromptOut(
        id=row["id"],
        name=row["name"],
        text=row["text"],
        estimated_output_tokens=row["estimated_output_tokens"],
        model=row["model"],
        effort=row["effort"],
        max_output_tokens=row["max_output_tokens"],
        created_at=row["created_at"],
        entity_kind=row["entity_kind"],
        stance_labels=stance_labels(row),
    )


def _check_labels(labels: list[str] | None) -> None:
    if labels is None:
        return
    if len(labels) > MAX_STANCE_LABELS:
        raise HTTPException(
            status_code=422, detail=f"At most {MAX_STANCE_LABELS} stance labels"
        )
    if len({label.casefold() for label in labels}) != len(labels):
        raise HTTPException(status_code=422, detail="Stance labels must be unique")


def _resolve_model(family: str, request: Request) -> ClaudeModel:
    model = request.app.state.catalog.resolve(family)
    if model is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown model {family!r}. Choose one of: {', '.join(FAMILIES)}",
        )
    return model


@router.get("", response_model=list[PromptOut])
def list_prompts(request: Request) -> list[PromptOut]:
    return [_to_prompt(row) for row in request.app.state.db.list_prompts()]


@router.post("", response_model=PromptOut, status_code=201)
def add_prompt(body: PromptIn, request: Request) -> PromptOut:
    name = body.name.strip()
    text = body.text.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Prompt name cannot be empty")
    if not text:
        raise HTTPException(status_code=422, detail="Prompt text cannot be empty")
    _check_labels(body.stance_labels)
    model = _resolve_model(body.model, request)
    if model.efforts and body.effort not in model.efforts:
        raise HTTPException(status_code=422, detail=f"Choose an effort for {model.name}")
    try:
        row = request.app.state.db.add_prompt(
            name,
            text,
            body.estimated_output_tokens,
            entity_kind=(body.entity_kind or "").strip(),
            stance_labels=body.stance_labels,
            model=body.model,
            effort=body.effort if model.efforts else None,
            max_output_tokens=body.max_output_tokens,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Prompt {name!r} already exists")
    return _to_prompt(row)


@router.patch("/{prompt_id}", response_model=PromptOut)
def update_prompt(prompt_id: int, body: PromptPatch, request: Request) -> PromptOut:
    name = body.name.strip() if body.name is not None else None
    if name is not None and not name:
        raise HTTPException(status_code=422, detail="Prompt name cannot be empty")
    text = body.text.strip() if body.text is not None else None
    if text is not None and not text:
        raise HTTPException(status_code=422, detail="Prompt text cannot be empty")
    _check_labels(body.stance_labels)
    if body.model is not None:
        _resolve_model(body.model, request)
    try:
        row = request.app.state.db.update_prompt(
            prompt_id,
            name=name,
            text=text,
            estimated_output_tokens=body.estimated_output_tokens,
            entity_kind=body.entity_kind.strip() if body.entity_kind is not None else None,
            stance_labels=body.stance_labels,
            model=body.model,
            effort=body.effort,
            max_output_tokens=body.max_output_tokens,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Prompt {name!r} already exists")
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return _to_prompt(row)


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int, request: Request) -> None:
    db = request.app.state.db
    row = db.get_prompt(prompt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    users = db.channels_using_prompt(row["name"])
    if users:
        labels = ", ".join(u["label"] for u in users)
        raise HTTPException(
            status_code=409,
            detail=f"Prompt {row['name']!r} is in use by: {labels}. "
            "Give those channels another prompt first.",
        )
    db.delete_prompt(prompt_id)
