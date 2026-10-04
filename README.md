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
- Choose the **model family (Fable, Opus, Sonnet or Haiku), effort and output cap per prompt**, and per question in the Ask tab — a family always runs on its newest model, so a new Claude model needs no configuration
- **Settings in the UI**, stored in the database and applied without a restart — no config file to maintain
- Give a prompt an **entity kind and stance labels** (coin + bullish/bearish,
  product + recommend/avoid, …) and every video also yields **structured
  mentions**: entity, stance, confidence, quote and timestamp. The Mentions tab
  shows the current stance per entity, flags changes, and links each quote to
  the exact second in the video
- **Search** transcripts and summaries (SQLite FTS5) with highlighted snippets
  that link into the video where the words were spoken
- **Ask** a question across many videos: the mentions, summaries and matching
  transcript excerpts in the chosen period are sent to Claude, and the answer
  cites the videos it used — with the same estimate-then-approve flow
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
- Node.js 20+ and [pnpm](https://pnpm.io/installation) 10+ (the frontend's
  package manager; `corepack enable pnpm` works too)
- An Anthropic API key ([platform.claude.com](https://platform.claude.com/))

## Setup

```bash
git clone <this repo> && cd youtube-transcripts

make install              # creates .venv, installs backend + frontend deps

cp backend/.env.example backend/.env    # then put your ANTHROPIC_API_KEY in it
```

On its first start the backend creates `~/.config/yt-summarizer/config.yaml`
from the `backend/config.example.yaml` template (honouring `$XDG_CONFIG_HOME`)
and logs where it put it. That file only says where the database lives; the
checkout is never written to. Settings, channels and prompts are managed in the
UI and stored in the database.

Secrets go in a `.env` next to the config file
(`~/.config/yt-summarizer/.env`); a `backend/.env` is still picked up as a
fallback. `$YT_SUMMARIZER_CONFIG` points directly at a config file and
overrides everything (no copy is made).

## Running

Two processes, one terminal each:

```bash
make backend    # uvicorn on http://localhost:8000 (API docs at /docs)
make frontend   # Vite on http://localhost:5173 — open this in your browser
```

For an always-on box (a Raspberry Pi, say), `make start` launches both detached
so they survive logging out, with `make status`, `make logs` and `make stop` to
manage them. Logs and PID files go to `$XDG_STATE_HOME/yt-summarizer`
(`~/.local/state/yt-summarizer` by default) — nothing is written inside the
checkout.

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
6. **Browse summaries** — the *Summaries* tab renders each summary's Markdown, with model/prompt/cost/token badges and the stored transcript on demand. "Show stats" splits the output into thinking and response tokens and shows how much of the output cap was used, the assumed output against the actual, and the duration — use it to tune the prompt's effort, max output and est. output.

## Settings

Everything is edited in the UI and stored in the database: channels, prompts and digest recipients in their own dialogs, the global settings in "Settings". A save applies at once, without a restart.

| Setting | Purpose |
| --- | --- |
| Models and prices | $/1M input and output tokens for each model family — used for every cost estimate and for the daily budget |
| Videos listed per channel | How many recent videos/lives to list |
| Seconds between YouTube requests | Minimum pause between YouTube requests |
| Transcript languages | Preferred transcript languages, in order; falls back to the original-language auto captions |
| Cookies file | Optional Netscape-format cookies file for higher rate limits |
| Ask: context ceiling / assumed answer length / max output | Context sent with a question, assumed answer length for the estimate, and hard cap on thinking plus answer |
| Check channels automatically | Turn the background monitor on |
| Schedule | 5-field cron expression for when to check, in the **server's local time** (default `0 * * * *` — every hour on the hour) |
| Also check when the server starts | Run one catch-up cycle at startup (on by default) |
| Recent videos checked / ignore videos older than | How far back each cycle looks |
| Daily budget | Hard spend cap per UTC day across all channels |
| Digest sender / subject prefix | Sender address (on a domain verified at Resend) and subject prefix of the digest |

**Models.** A prompt or a question chooses a family — Fable, Opus, Sonnet or Haiku — and always runs on the newest model of that family. The list comes from Anthropic's Models API (it needs your API key; without it the models known to this version are offered), is refreshed every few hours, and "Check for new models" in Settings refreshes it on demand. Anthropic's API does not report prices, so they are a setting: when a family moves to a new model the app asks you to check its price, and keeps using the old one until you save.

Each prompt carries its own model family, effort and output cap, set in "Manage prompts". A prompt without a model cannot run, nor one without an effort when its model takes one (Haiku takes none). The output cap covers thinking plus response; raise it when you raise the effort.

**`config.yaml`** (`~/.config/yt-summarizer/config.yaml`) holds a single optional key, `database`: the SQLite file path. Unset (default) → `$XDG_DATA_HOME/yt-summarizer/videos.db` (i.e. `~/.local/share/yt-summarizer/videos.db`). An absolute path is used as-is; a relative path resolves under the XDG data dir. A `config.yaml` from an older version that still holds settings is imported into the database on the first start, then ignored; prompts that named a model id move to its family.

Secrets live in a `.env` next to the config file
(`~/.config/yt-summarizer/.env`, or `backend/.env` as a fallback) —
`ANTHROPIC_API_KEY` and, for digests, `RESEND_API_KEY` — never in
`config.yaml`.

## Data & migrating

The database lives at `~/.local/share/yt-summarizer/videos.db` (following the
XDG Base Directory spec; override with `$XDG_DATA_HOME` or the `database:`
config key).

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
  your IP. Requests are already paced ("Seconds between YouTube requests" in
  Settings, default 2 s) and retried once after a 20 s backoff; when the
  429 persists, the remaining videos in the batch are skipped so the
  throttling isn't made worse. Wait a few minutes and rerun the estimate —
  already-summarized videos reuse their stored transcript and cost no YouTube
  requests. If it keeps happening, raise that pause or set a cookies file in
  Settings (logged-in requests get higher limits).
- **No videos found / yt-dlp errors** — YouTube changes its site regularly;
  update with `.venv/bin/pip install -U yt-dlp`.
- **"Anthropic authentication failed" (HTTP 502)** — check that `backend/.env`
  exists and contains a valid `ANTHROPIC_API_KEY`.
- **"A summarization job is already running" (HTTP 409)** — only one job runs
  at a time; wait for it to finish.
- **"This estimate has expired" (HTTP 410)** — estimates are kept in memory
  and consumed on approval; after a backend restart just run the estimate
  again.
- **Costs look wrong** — the prices in Settings drive the cost math; keep them
  in sync with the official pricing page.
- **Reprocess a video** — in the *Process videos* tab, tick an
  already-processed video (its status flips to "Reprocess") and run the
  estimate as usual. The stored transcript is reused, and the new summary
  overwrites the old one.
