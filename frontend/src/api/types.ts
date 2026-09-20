// TypeScript mirrors of the backend's Pydantic schemas (backend/app/schemas.py).

export interface Prompt {
  id: number
  name: string
  text: string
  estimated_output_tokens: number
  created_at: string
  entity_kind: string | null // what the prompt extracts (coin, stock, product…)
  stance_labels: string[] // empty = summary only, no extraction
}

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
  input_tokens: number | null
  estimated_output_tokens: number | null
  cost_usd: number | null
}

export interface Estimate {
  estimate_id: string
  model: string
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
  mentions: Mention[]
}

export interface SummaryDetail extends Summary {
  transcript: string
}

export interface Meta {
  model: string
  max_videos_fetch: number
  monitoring_enabled: boolean
  monitor_schedule: string
  monitor_next_run: string | null
  daily_budget_usd: number
  spend_today_usd: number
}
