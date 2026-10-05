"""Pydantic models for the REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from yt_summarizer.config import DEFAULT_MAX_OUTPUT_TOKENS
from yt_summarizer.models import Effort
from yt_summarizer.transcripts import TranscriptSource

MAX_STANCE_LABELS = 20


def _clean_labels(labels: list[str] | None) -> list[str] | None:
    if labels is None:
        return None
    return [label.strip() for label in labels if label.strip()]


class PromptIn(BaseModel):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    estimated_output_tokens: int = Field(default=2000, ge=1)
    model: str = Field(min_length=1)  # a model family: the newest model of it is used
    effort: Effort | None = None  # required when the model takes one
    max_output_tokens: int = Field(default=DEFAULT_MAX_OUTPUT_TOKENS, ge=1)
    # Extraction is off while stance_labels is empty.
    entity_kind: str | None = None
    stance_labels: list[str] = []

    @field_validator("stance_labels")
    @classmethod
    def _labels(cls, value: list[str]) -> list[str]:
        return _clean_labels(value) or []


class PromptPatch(BaseModel):
    # Absent = no change.
    name: str | None = Field(default=None, min_length=1)
    text: str | None = Field(default=None, min_length=1)
    estimated_output_tokens: int | None = Field(default=None, ge=1)
    model: str | None = Field(default=None, min_length=1)
    effort: Effort | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    entity_kind: str | None = None
    stance_labels: list[str] | None = None

    @field_validator("stance_labels")
    @classmethod
    def _labels(cls, value: list[str] | None) -> list[str] | None:
        return _clean_labels(value)


class PromptOut(BaseModel):
    id: int
    name: str
    text: str
    estimated_output_tokens: int
    # None on prompts created before model and effort were chosen per prompt.
    model: str | None
    effort: str | None
    max_output_tokens: int
    created_at: str
    entity_kind: str | None = None
    stance_labels: list[str] = []


class ChannelIn(BaseModel):
    input: str
    label: str | None = None  # defaults to the channel name found on YouTube
    prompt_name: str  # required — the prompt (by name) used for this channel
    notify_emails: list[str] = []  # digest recipients for the background monitor


class ChannelPatch(BaseModel):
    # Absent = no change. For notify_emails, pass [] to clear all recipients.
    prompt_name: str | None = None
    notify_emails: list[str] | None = None


class ChannelOut(BaseModel):
    id: int
    input: str
    label: str
    created_at: str
    prompt_name: str | None = None
    notify_emails: list[str] = []


class VideoOut(BaseModel):
    video_id: str
    title: str
    published_at: str | None  # UTC ISO 8601; rendered in the viewer's local time
    url: str
    processed: bool
    date_approximate: bool = False  # True when published_at is only an estimate


class VideoListOut(BaseModel):
    channel: ChannelOut
    videos: list[VideoOut]


class EstimateRequest(BaseModel):
    channel_id: int
    video_ids: list[str] = Field(min_length=1)
    # The prompt is taken from the channel's chosen prompt — not requested here.


class EstimateItemOut(BaseModel):
    video_id: str
    title: str
    published_at: str | None
    url: str
    status: Literal["ok", "no_transcript"]
    detail: str | None = None
    transcript_source: TranscriptSource | None = None
    input_tokens: int | None = None
    estimated_output_tokens: int | None = None
    cost_usd: float | None = None


class EstimateOut(BaseModel):
    estimate_id: str
    model: str  # the model id the family resolved to
    effort: str | None
    prompt_name: str
    items: list[EstimateItemOut]
    total_input_tokens: int
    total_cost_usd: float


class JobCreate(BaseModel):
    estimate_id: str
    video_ids: list[str] | None = None  # subset of the estimate's "ok" items; default all


class JobCreated(BaseModel):
    job_id: str


class JobItemOut(BaseModel):
    video_id: str
    title: str
    status: Literal["queued", "processing", "done", "failed"]
    error: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float | None = None


class JobOut(BaseModel):
    job_id: str
    status: Literal["running", "done"]
    created_at: str
    items: list[JobItemOut]
    total_cost_usd: float


class MentionOut(BaseModel):
    video_id: str
    entity: str
    entity_key: str
    stance: str
    confidence: str
    rationale: str | None = None
    quote: str | None = None
    timestamp_seconds: int | None = None
    published_at: str | None = None
    channel_id: int | None = None
    title: str | None = None
    url: str | None = None


class EntityOut(BaseModel):
    entity: str
    entity_key: str
    latest_stance: str
    latest_at: str | None
    latest_video_id: str
    previous_stance: str | None
    previous_at: str | None
    mention_count: int
    video_count: int


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1)
    model: str = Field(min_length=1)
    effort: Effort | None = None
    channel_id: int | None = None  # None = every channel
    since: str | None = None  # UTC ISO 8601
    until: str | None = None


class QuestionAsk(BaseModel):
    estimate_id: str


class SourceOut(BaseModel):
    number: int
    kind: Literal["mention", "summary", "excerpt"]
    video_id: str
    title: str
    url: str
    published_at: str | None
    start_seconds: int | None = None


class QuestionEstimateOut(BaseModel):
    estimate_id: str
    model: str
    effort: str | None
    question: str
    mention_count: int
    summary_count: int
    excerpt_count: int
    input_tokens: int
    estimated_output_tokens: int
    cost_usd: float


class QuestionOut(BaseModel):
    id: int
    channel_id: int | None
    question: str
    since: str | None
    until: str | None
    answer: str
    sources: list[SourceOut]
    model: str
    tokens_input: int | None
    tokens_output: int | None
    cost_usd: float | None
    created_at: str


class SearchHitOut(BaseModel):
    video_id: str
    kind: Literal["transcript", "summary"]
    start_seconds: int | None
    snippet: str  # highlights delimited by \x02 and \x03
    title: str
    url: str
    published_at: str | None
    channel_id: int | None


class SummaryOut(BaseModel):
    id: int
    video_id: str
    title: str
    url: str
    published_at: str | None
    prompt_name: str
    model: str
    ai_response: str
    tokens_input: int | None
    tokens_output: int | None
    cost_usd: float | None
    processed_at: str
    channel_id: int | None
    transcript_source: TranscriptSource | None = None
    mentions: list[MentionOut] = []
    # How the summary was produced; None on rows saved before these were recorded.
    effort: str | None = None
    max_output_tokens: int | None = None
    estimated_output_tokens: int | None = None
    tokens_thinking: int | None = None  # part of tokens_output
    stop_reason: str | None = None
    duration_ms: int | None = None


class SummaryDetailOut(SummaryOut):
    transcript: str


class ModelOut(BaseModel):
    family: str  # what a prompt or a question chooses
    id: str  # the newest model of that family
    name: str
    efforts: list[str]  # empty when the model takes no effort level
    price_confirmed: bool  # False once the family moved to a model its price was not saved for


class PricingBody(BaseModel):
    input: float
    output: float


class MonitoringBody(BaseModel):
    enabled: bool
    schedule: str  # cron expression, evaluated in the server's local time
    run_on_start: bool
    max_videos_check: int
    max_age_hours: int
    daily_budget_usd: float
    resend_from: str
    subject_prefix: str


class AskBody(BaseModel):
    max_context_tokens: int
    estimated_output_tokens: int
    max_output_tokens: int


class SettingsBody(BaseModel):
    max_videos_fetch: int
    transcript_languages: list[str]
    youtube_request_interval: float
    cookies_file: str | None = None
    pricing: dict[str, PricingBody]  # keyed by model family
    monitoring: MonitoringBody
    ask: AskBody


class MetaOut(BaseModel):
    models: list[ModelOut]
    max_videos_fetch: int
    monitoring_enabled: bool
    monitor_schedule: str  # cron expression, evaluated in the server's local time
    monitor_next_run: str | None  # UTC ISO; None when the monitor isn't running
    daily_budget_usd: float
    spend_today_usd: float


class MonitorRunOut(BaseModel):
    started: bool  # False if a job/cycle was already running
    detail: str
