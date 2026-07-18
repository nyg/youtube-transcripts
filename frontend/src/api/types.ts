// TypeScript mirrors of the backend's Pydantic schemas (backend/app/schemas.py).

export interface Channel {
  id: number
  input: string
  label: string
  created_at: string
}

export interface Video {
  video_id: string
  title: string
  published_at: string | null
  url: string
  processed: boolean
}

export interface VideoList {
  channel: Channel
  videos: Video[]
}

export interface EstimateRequest {
  channel_id: number
  video_ids: string[]
  prompt_name?: string
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
}

export interface SummaryDetail extends Summary {
  transcript: string
}

export interface Meta {
  model: string
  prompts: string[]
  active_prompt: string
  estimated_output_tokens: number
  max_videos_fetch: number
}
