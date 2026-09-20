"""Pydantic models for the REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_STANCE_LABELS = 20


def _clean_labels(labels: list[str] | None) -> list[str] | None:
    if labels is None:
        return None
    return [label.strip() for label in labels if label.strip()]


class PromptIn(BaseModel):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    estimated_output_tokens: int = Field(default=2000, ge=1)
    # Extraction is off while stance_labels is empty.
    entity_kind: str | None = None
    stance_labels: list[str] = []

    @field_validator("stance_labels")
    @classmethod
    def _labels(cls, value: list[str]) -> list[str]:
        return _clean_labels(value) or []


class PromptPatch(BaseModel):
    # Name is immutable (channels reference a prompt by name). Absent = no change.
    text: str | None = Field(default=None, min_length=1)
    estimated_output_tokens: int | None = Field(default=None, ge=1)
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
    input_tokens: int | None = None
    estimated_output_tokens: int | None = None
    cost_usd: float | None = None  # None also when the model has no pricing entry


class EstimateOut(BaseModel):
    estimate_id: str
    model: str
    prompt_name: str
    items: list[EstimateItemOut]
    total_input_tokens: int
    total_cost_usd: float | None


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
    mentions: list[MentionOut] = []


class SummaryDetailOut(SummaryOut):
    transcript: str


class MetaOut(BaseModel):
    model: str
    max_videos_fetch: int
    monitoring_enabled: bool
    monitor_schedule: str  # cron expression, evaluated in the server's local time
    monitor_next_run: str | None  # UTC ISO; None when the monitor isn't running
    daily_budget_usd: float
    spend_today_usd: float


class MonitorRunOut(BaseModel):
    started: bool  # False if a job/cycle was already running
    detail: str
