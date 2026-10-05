// TypeScript mirrors of the backend's Pydantic schemas (backend/app/schemas.py).

export interface Prompt {
  id: number
  name: string
  text: string
  estimated_output_tokens: number
  model: string | null // a model family; null until chosen: the prompt cannot run without it
  effort: string | null // null also when the model takes no effort level
  max_output_tokens: number // hard cap on thinking plus response
  created_at: string
  entity_kind: string | null // what the prompt extracts (coin, stock, product…)
  stance_labels: string[] // empty = summary only, no extraction
}

export type TranscriptSource = "manual" | "auto"

export interface Mention {
  video_id: string
  entity: string
  entity_key: string
  stance: string
  confidence: string
  rationale: string | null
  quote: string | null
  timestamp_seconds: number | null
  published_at: string | null
  channel_id: number | null
  title: string | null
  url: string | null
}

export interface Source {
  number: number
  kind: "mention" | "summary" | "excerpt"
  video_id: string
  title: string
  url: string
  published_at: string | null
  start_seconds: number | null
}

export interface QuestionEstimate {
  estimate_id: string
  model: string
  effort: string | null
  question: string
  mention_count: number
  summary_count: number
  excerpt_count: number
  input_tokens: number
  estimated_output_tokens: number
  cost_usd: number | null
}

export interface Question {
  id: number
  channel_id: number | null
  question: string
  since: string | null
  until: string | null
  answer: string
  sources: Source[]
  model: string
  tokens_input: number | null
  tokens_output: number | null
  cost_usd: number | null
  created_at: string
}

export interface SearchHit {
  video_id: string
  kind: "transcript" | "summary"
  start_seconds: number | null
  snippet: string // highlights delimited by \x02 and \x03
  title: string
  url: string
  published_at: string | null
  channel_id: number | null
}

export interface Entity {
  entity: string
  entity_key: string
  latest_stance: string
  latest_at: string | null
  latest_video_id: string
  previous_stance: string | null
  previous_at: string | null
  mention_count: number
  video_count: number
}

export interface Channel {
  id: number
  input: string
  label: string
  created_at: string
  prompt_name: string | null // the prompt (by name) this channel uses
  notify_emails: string[] // digest recipients for the background monitor
}

export interface Video {
  video_id: string
  title: string
  published_at: string | null
  url: string
  processed: boolean
  date_approximate: boolean
}

export interface VideoList {
  channel: Channel
  videos: Video[]
}

export interface EstimateRequest {
  channel_id: number
  video_ids: string[]
}

export interface EstimateItem {
  video_id: string
  title: string
  published_at: string | null
  url: string
  status: "ok" | "no_transcript"
  detail: string | null
  transcript_source: TranscriptSource | null
  input_tokens: number | null
  estimated_output_tokens: number | null
  cost_usd: number | null
}

export interface Estimate {
  estimate_id: string
  model: string
  effort: string | null
  prompt_name: string
  items: EstimateItem[]
  total_input_tokens: number
  total_cost_usd: number | null
}

export interface JobItem {
  video_id: string
  title: string
  status: "queued" | "processing" | "done" | "failed"
  error: string | null
  tokens_input: number | null
  tokens_output: number | null
  cost_usd: number | null
}

export interface Job {
  job_id: string
  status: "running" | "done"
  created_at: string
  items: JobItem[]
  total_cost_usd: number
}

export interface Summary {
  id: number
  video_id: string
  title: string
  url: string
  published_at: string | null
  prompt_name: string
  model: string
  ai_response: string
  tokens_input: number | null
  tokens_output: number | null
  cost_usd: number | null
  processed_at: string
  channel_id: number | null
  transcript_source: TranscriptSource | null
  mentions: Mention[]
  // How the summary was produced; null on summaries saved before these were recorded.
  effort: string | null
  max_output_tokens: number | null
  estimated_output_tokens: number | null
  tokens_thinking: number | null // part of tokens_output
  stop_reason: string | null
  duration_ms: number | null
}

export interface SummaryDetail extends Summary {
  transcript: string
}

export interface ClaudeModel {
  family: string // what a prompt or a question chooses
  id: string // the newest model of that family
  name: string
  efforts: string[] // empty when the model takes no effort level
  price_confirmed: boolean // false once the family moved to a model its price was not saved for
}

export interface Settings {
  max_videos_fetch: number
  transcript_languages: string[]
  youtube_request_interval: number
  cookies_file: string | null
  pricing: Record<string, { input: number; output: number }> // USD per 1M tokens, by model family
  monitoring: {
    enabled: boolean
    schedule: string // cron expression, evaluated in the server's local time
    run_on_start: boolean
    max_videos_check: number
    max_age_hours: number
    daily_budget_usd: number
    resend_from: string
    subject_prefix: string
  }
  ask: {
    max_context_tokens: number
    estimated_output_tokens: number
    max_output_tokens: number
  }
}

export interface Meta {
  models: ClaudeModel[]
  max_videos_fetch: number
  monitoring_enabled: boolean
  monitor_schedule: string
  monitor_next_run: string | null
  daily_budget_usd: number
  spend_today_usd: number
}
