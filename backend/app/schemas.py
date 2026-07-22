"""Pydantic models for the REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PromptIn(BaseModel):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    estimated_output_tokens: int = Field(default=2000, ge=1)


class PromptPatch(BaseModel):
    # Name is immutable (channels reference a prompt by name). Absent = no change.
    text: str | None = Field(default=None, min_length=1)
    estimated_output_tokens: int | None = Field(default=None, ge=1)


class PromptOut(BaseModel):
    id: int
    name: str
    text: str
    estimated_output_tokens: int
    created_at: str


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


class SummaryDetailOut(SummaryOut):
    transcript: str


class MetaOut(BaseModel):
    model: str
    max_videos_fetch: int
    monitoring_enabled: bool
    daily_budget_usd: float
    spend_today_usd: float


class MonitorRunOut(BaseModel):
    started: bool  # False if a job/cycle was already running
    detail: str
