"""Pydantic models for the REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChannelIn(BaseModel):
    input: str
    label: str | None = None  # defaults to the channel name found on YouTube


class ChannelOut(BaseModel):
    id: int
    input: str
    label: str
    created_at: str


class VideoOut(BaseModel):
    video_id: str
    title: str
    published_at: str | None
    url: str
    processed: bool


class VideoListOut(BaseModel):
    channel: ChannelOut
    videos: list[VideoOut]


class EstimateRequest(BaseModel):
    channel_id: int
    video_ids: list[str] = Field(min_length=1)
    prompt_name: str | None = None  # defaults to the config's active_prompt


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
    prompts: list[str]
    active_prompt: str
    estimated_output_tokens: int
    max_videos_fetch: int
