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

The bundled `backend/config.yaml` is used out of the box. To keep your own
config outside the checkout, copy it to `~/.config/yt-summarizer/config.yaml`
(honouring `$XDG_CONFIG_HOME`); it takes precedence when present. Secrets go in
a `.env` next to whichever config file is used. `$YT_SUMMARIZER_CONFIG` points
directly at a config file and overrides both.

## Running

Two processes, one terminal each:

```bash
make backend    # uvicorn on http://localhost:8000 (API docs at /docs)
make frontend   # Vite on http://localhost:5173 — open this in your browser
```

## Usage

1. **Add channels** — "Manage channels", enter an `@handle`, `UC…` channel ID,
   or channel URL. Switch channels with the dropdown.
2. **Select videos** — the *Process videos* tab lists recent videos with their
   real publish dates (shown in your local time), already-processed ones
   marked. Tick the ones you want (the header checkbox selects all new); ticking
   an already-processed video reprocesses it.
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
| `database` | SQLite file path. Unset (default) → `$XDG_DATA_HOME/yt-summarizer/videos.db` (i.e. `~/.local/share/yt-summarizer/videos.db`). An absolute path is used as-is; a relative path resolves under the XDG data dir |

Secrets live in a `.env` next to the config file (`backend/.env` for the
bundled config; `~/.config/yt-summarizer/.env` for an XDG one) — only
`ANTHROPIC_API_KEY` — never in `config.yaml`.

## Data & migrating

The database lives at `~/.local/share/yt-summarizer/videos.db` (following the
XDG Base Directory spec; override with `$XDG_DATA_HOME` or the `database:`
config key). On the first start, if that file does not exist yet but a pre-XDG
`backend/data/videos.db` does, it is copied over automatically so your
processed history is preserved (the original is left untouched).

The schema is upgraded automatically on the next backend start (a `channels`
table and a `channel_id` column are added).

## How it works

1. yt-dlp lists the channel's `/videos` and `/streams` tabs (flat extraction —
   two cheap requests, no API key). Shorts live in a separate tab and are never
   fetched. The flat listing only carries approximate dates, so they are
   upgraded to exact publish times from the channel's RSS feed (one more cheap
   request covering the ~15 newest videos); already-processed videos reuse the
   exact date stored in the database. Anything still approximate is marked with
   a "~". All times are sent as UTC and rendered in the viewer's local time.
2. The list is diffed against the SQLite database so already-processed videos
   are marked; they can still be ticked to reprocess them (reusing the stored
   transcript).
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
  uploader, or not yet generated for a very recent upload/live). Skipped
  videos stay unprocessed and can be retried later.
- **"YouTube rate limit (HTTP 429)"** — YouTube is throttling requests from
  your IP. Requests are already paced (`youtube_request_interval` in
  `config.yaml`, default 2 s) and retried once after a 20 s backoff; when the
  429 persists, the remaining videos in the batch are skipped so the
  throttling isn't made worse. Wait a few minutes and rerun the estimate —
  already-summarized videos reuse their stored transcript and cost no YouTube
  requests. If it keeps happening, raise `youtube_request_interval` or set
  `cookies_file` (logged-in requests get higher limits).
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
- **Reprocess a video** — in the *Process videos* tab, tick an
  already-processed video (its status flips to "Reprocess") and run the
  estimate as usual. The stored transcript is reused, and the new summary
  overwrites the old one.
