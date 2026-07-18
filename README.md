# YouTube Transcript Summarizer

Summarize the recent videos of your favorite YouTube channels with Claude, from
a local web app.

- **React + shadcn/ui frontend** (Vite) talking to a **FastAPI backend**
- Manage multiple channels in the UI — added channels are verified on YouTube
- Lists a channel's recent **uploads and live VODs** (Shorts are excluded) via
  [yt-dlp](https://github.com/yt-dlp/yt-dlp) — **no YouTube API key needed**
- Fetches transcripts through yt-dlp's caption download (manual subtitles
  preferred, auto-generated as fallback)
- Select videos → see an **exact input token count** (Anthropic's free
  `count_tokens` endpoint) and a **cost estimate** → nothing is billed until
  you explicitly approve
- Watch per-video progress while summaries are generated, then browse them
  with rendered Markdown and stored transcripts
- Everything is stored in **SQLite** — videos are never processed twice

## Architecture

```
frontend/  Vite + React + TypeScript + Tailwind + shadcn/ui   (dev server :5173)
backend/   FastAPI + uvicorn                                  (API server :8000)
           ├── app/            REST API, estimate store, job worker
           └── yt_summarizer/  domain modules (yt-dlp, transcripts, Claude, SQLite)
```

The Vite dev server proxies `/api/*` to the backend, so the browser only ever
talks to `localhost:5173`.

## Requirements

- Python 3.11+ (3.14 tested)
- Node.js 20+
- An Anthropic API key ([platform.claude.com](https://platform.claude.com/))

## Setup

```bash
git clone <this repo> && cd youtube-transcripts

make install              # creates .venv, installs backend + frontend deps

cp backend/.env.example backend/.env    # then put your ANTHROPIC_API_KEY in it
```

Optionally edit `backend/config.yaml` — the `channel` there is seeded into the
database on first start; after that, channels are managed entirely in the UI.

## Running

Two processes, one terminal each:

```bash
make backend    # uvicorn on http://localhost:8000 (API docs at /docs)
make frontend   # Vite on http://localhost:5173 — open this in your browser
```

## Usage

1. **Add channels** — "Manage channels", enter an `@handle`, `UC…` channel ID,
   or channel URL. Switch channels with the dropdown.
2. **Select videos** — the *Process videos* tab lists recent videos, with
   already-processed ones marked. Tick the ones you want (the header checkbox
   selects all new).
3. **Estimate (free)** — "Estimate cost" fetches transcripts and counts input
   tokens server-side with Anthropic's free endpoint. Videos without
   transcripts are skipped and shown as such. You can switch the prompt here.
4. **Approve (billed)** — the approve button shows the estimated total. Only
   after clicking it are transcripts sent to Claude — exactly the ones you saw
   in the estimate.
5. **Watch progress** — each video goes queued → processing → done/failed;
   actual cost per video is shown when finished.
6. **Browse summaries** — the *Summaries* tab renders each summary's Markdown,
   with model/prompt/cost/token badges and the stored transcript on demand.

## Configuration (`backend/config.yaml`)

| Key | Purpose |
| --- | --- |
| `channel` | Seed channel, imported into the DB on first start only |
| `max_videos_fetch` | How many recent videos/lives to list |
| `transcript_languages` | Preferred transcript languages, in order; falls back to the original-language auto captions |
| `model` | Claude model ID (default `claude-opus-4-8`) |
| `max_output_tokens` | Hard cap on response length |
| `estimated_output_tokens` | Assumed output size for the *pre-call* cost estimate |
| `pricing` | $/1M input & output tokens per model — used for cost math |
| `active_prompt` / `prompts` | Named system prompts; `active_prompt` is the default, selectable per run in the UI |
| `database` | SQLite file path (default `data/videos.db`, relative to `backend/`) |

Secrets live in `backend/.env` (only `ANTHROPIC_API_KEY`), never in
`config.yaml`.

## Data & migrating from the CLI version

The database now lives at `backend/data/videos.db`. If you used the old CLI
version, copy your existing database there to keep your processed history:

```bash
mkdir -p backend/data && cp data/videos.db backend/data/videos.db
```

The schema is upgraded automatically on the next backend start (a `channels`
table and a `channel_id` column are added; old summaries appear under
"All channels").

## How it works

1. yt-dlp lists the channel's `/videos` and `/streams` tabs (flat extraction —
   two cheap requests, no API key). Shorts live in a separate tab and are never
   fetched.
2. The list is diffed against the SQLite database, so already-processed videos
   are marked and can't be re-selected.
3. The estimate endpoint fetches each video's exact metadata and transcript,
   and computes the *exact* input token count with Anthropic's free
   `count_tokens` endpoint. The fetched transcripts are kept server-side,
   keyed by the estimate.
4. Approving creates a job from that stored estimate — what you approved is
   exactly what is billed. Each transcript is sent to Claude (streaming, so
   long transcripts don't hit HTTP timeouts); actual token usage and cost are
   stored with the result. The frontend polls the job status once per second.
5. `video_summaries` table: `video_id` (unique), `title`, `url`,
   `published_at`, `transcript`, `prompt_name`, `model`, `ai_response`,
   `tokens_input`, `tokens_output`, `cost_usd`, `processed_at`, `channel_id`.

## Troubleshooting

- **"No transcript — skipped"** — the video has no captions (disabled by the
  uploader, or not yet generated for a very recent upload/live), or YouTube is
  rate-limiting caption downloads from your IP (`HTTP Error 429` in the
  detail). Skipped videos stay unprocessed and can be retried later.
- **No videos found / yt-dlp errors** — YouTube changes its site regularly;
  update with `.venv/bin/pip install -U yt-dlp`.
- **"Anthropic authentication failed" (HTTP 502)** — check that `backend/.env`
  exists and contains a valid `ANTHROPIC_API_KEY`.
- **"A summarization job is already running" (HTTP 409)** — only one job runs
  at a time; wait for it to finish.
- **"This estimate has expired" (HTTP 410)** — estimates are kept in memory
  and consumed on approval; after a backend restart just run the estimate
  again.
- **Costs look wrong** — the `pricing` table in `config.yaml` is only used for
  display; keep it in sync with the official pricing page.
- **Reprocess a video** — delete its row:
  `sqlite3 backend/data/videos.db "DELETE FROM video_summaries WHERE video_id='...'"`.
