"""Ask a question across a channel's videos.

Same contract as summarization: an estimate is produced first (free), the user
approves the shown cost, and only then is the question sent to Claude. The
answer cites its sources as [n], and its cost counts toward the daily budget.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request

from yt_summarizer import analysis

from ..estimates import PreparedQuestion
from ..schemas import (
    QuestionAsk,
    QuestionEstimateOut,
    QuestionOut,
    QuestionRequest,
    SourceOut,
)

router = APIRouter(prefix="/api/questions")


def _sources_out(sources: list[analysis.Source]) -> list[SourceOut]:
    return [SourceOut(**vars(source)) for source in sources]


@router.post("/estimate", response_model=QuestionEstimateOut)
def estimate_question(body: QuestionRequest, request: Request) -> QuestionEstimateOut:
    state = request.app.state
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Ask a question first")

    context = analysis.build_context(
        state.db,
        question,
        channel_id=body.channel_id,
        since=body.since,
        until=body.until,
        max_tokens=state.config.ask.max_context_tokens,
    )
    if not context.sources:
        raise HTTPException(
            status_code=422,
            detail="Nothing to answer from — no summaries or mentions in this period.",
        )

    estimate = state.summarizer.estimate_answer(
        question, context.text, state.config.ask.estimated_output_tokens
    )
    estimate_id = uuid.uuid4().hex
    state.questions.add(
        estimate_id,
        PreparedQuestion(
            estimate_id=estimate_id,
            channel_id=body.channel_id,
            question=question,
            since=body.since,
            until=body.until,
            context=context.text,
            sources=context.sources,
            estimate=estimate,
        ),
    )
    return QuestionEstimateOut(
        estimate_id=estimate_id,
        model=state.config.model,
        question=question,
        mention_count=context.mention_count,
        summary_count=context.summary_count,
        excerpt_count=context.excerpt_count,
        input_tokens=estimate.input_tokens,
        estimated_output_tokens=estimate.estimated_output_tokens,
        cost_usd=estimate.cost_usd,
    )


@router.post("", response_model=QuestionOut)
def ask_question(body: QuestionAsk, request: Request) -> QuestionOut:
    state = request.app.state
    prepared = state.questions.pop(body.estimate_id)
    if prepared is None:
        raise HTTPException(
            status_code=410, detail="This estimate expired — run the estimate again."
        )

    result = state.summarizer.answer(prepared.question, prepared.context)
    sources = [vars(source) for source in prepared.sources]
    row = state.db.save_question(
        channel_id=prepared.channel_id,
        question=prepared.question,
        since=prepared.since,
        until=prepared.until,
        answer=result.text,
        sources=sources,
        model=state.config.model,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        cost_usd=result.cost_usd,
    )
    return _to_question(row)


@router.get("", response_model=list[QuestionOut])
def list_questions(request: Request, channel_id: int | None = None) -> list[QuestionOut]:
    return [_to_question(row) for row in request.app.state.db.list_questions(channel_id)]


@router.delete("/{question_id}", status_code=204)
def delete_question(question_id: int, request: Request) -> None:
    if not request.app.state.db.delete_question(question_id):
        raise HTTPException(status_code=404, detail="Question not found")


def _to_question(row) -> QuestionOut:
    return QuestionOut(
        id=row["id"],
        channel_id=row["channel_id"],
        question=row["question"],
        since=row["since"],
        until=row["until"],
        answer=row["answer"],
        sources=[SourceOut(**source) for source in json.loads(row["sources"] or "[]")],
        model=row["model"],
        tokens_input=row["tokens_input"],
        tokens_output=row["tokens_output"],
        cost_usd=row["cost_usd"],
        created_at=row["created_at"],
    )
