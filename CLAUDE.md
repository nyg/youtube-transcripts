# CLAUDE.md

Guidance for AI coding agents working in this repo. Keep it accurate — update it
when the architecture or conventions below change.

## What this is

A local web app that summarizes a YouTube channel's recent videos with Claude.
React + shadcn/ui frontend (Vite) talking to a FastAPI backend. Video listing
and transcripts come from **yt-dlp** (no YouTube API key). Nothing is billed to
Anthropic until the user approves an on-screen cost estimate.

## Layout

```
frontend/  Vite + React + TS + Tailwind + shadcn/ui       (dev server :5173)
backend/   FastAPI + uvicorn                               (API server :8000)
           ├── app/            REST API (routers/), estimate store, job worker
           │   ├── main.py         lifespan wiring: config, db, prompt bootstrap, jobs
           │   ├── routers/        channels, prompts, estimates, jobs, summaries,
           │   │                   mentions, meta
           │   ├── jobs.py         in-memory job registry + background worker
           │   ├── estimates.py    in-memory store carrying estimates -> jobs
           │   ├── prompts.py      resolves a prompt row -> Extraction spec
           │   └── schemas.py      Pydantic API models
           └── yt_summarizer/  domain modules
               ├── config.py       loads config.yaml + .env
               ├── paths.py        XDG resolution for config file & database
               ├── youtube_client.py  yt-dlp listing, RSS date enrichment
               ├── transcripts.py  caption track selection + json3 parsing (timed)
               ├── mentions.py     the Mention record + entity_key normalization
               ├── claude_client.py token counting, estimation, summarization
               ├── markdown_email.py  Markdown -> inline-styled HTML for digests
               ├── notifications.py   Resend transport
               └── database.py     SQLite persistence
```

The Vite dev server proxies `/api/*` to `http://localhost:8000`, so the browser
only talks to `:5173`.

## Run / test

```bash
make install          # .venv + backend deps + frontend pnpm install
make backend          # uvicorn --reload on :8000  (run from repo root)
make frontend         # Vite on :5173

# backend tests (pytest is in requirements.txt; install into .venv if missing)
cd backend && ../.venv/bin/python -m pytest -q

# frontend checks
cd frontend && pnpm run build   # tsc -b + vite build (type-checks)
cd frontend && pnpm run lint    # oxlint
```

Python 3.14 lives in `.venv`. Backend commands run from `backend/` using
`../.venv/bin/...`. `ANTHROPIC_API_KEY` goes in a `.env` next to the config file
(only needed for actual summarization, not for listing/browsing).

To verify UI changes without touching the user's real DB or hammering YouTube,
run the backend against an isolated `XDG_DATA_HOME`/`XDG_CONFIG_HOME` pointed at
a scratch dir and seed a test `videos.db` (see `yt_summarizer/database.py`).

## Conventions & gotchas (read before touching these areas)

**Paths are XDG-based** (`yt_summarizer/paths.py`). `ensure_config()` resolves
the config to `$XDG_CONFIG_HOME/yt-summarizer/config.yaml`, **creating it on
first run** by copying `backend/config.example.yaml` (or a leftover
`backend/config.yaml` from an older install, which holds real settings). The
checkout is never the live config — only the template is tracked, and
`backend/config.yaml` is gitignored. `$YT_SUMMARIZER_CONFIG` overrides and is
never copied to; a failed copy falls back to reading the template in place.
Database defaults to `$XDG_DATA_HOME/yt-summarizer/videos.db`, and the
Makefile's detached-mode logs and PID files to `$XDG_STATE_HOME/yt-summarizer`
(`STATE_DIR`; not `$XDG_RUNTIME_DIR`, which is wiped when the user's last
session ends — `make start` is meant to survive logout). Nothing the app or the
Makefile writes belongs inside the checkout: don't hardcode a repo-relative
database, config, or log path.

**The monitor is cron-scheduled in local time.** `monitoring.schedule` is a
5-field cron expression (croniter); `app/monitor.py` recomputes the next fire
time each iteration off `datetime.now().astimezone()`, so timing is wall-clock
stable and restart-independent. This is the one place local time is
authoritative — see the UTC rule below, which governs stored/served timestamps.
`monitoring.run_on_start` (default true) additionally runs one catch-up cycle at
startup. The legacy `interval_minutes` key is rejected with a `ConfigError`
rather than silently ignored.

**Channels and prompts live in the DB, not config.** Both are UI-managed CRUD
entities (`channels` and `prompts` tables; `routers/channels.py` /
`routers/prompts.py`; React `ChannelManagerDialog` / `PromptManagerDialog`).
`config.yaml` holds only global settings (model, pricing, YouTube pacing,
monitoring schedule/budget). A **prompt** carries its own text and
`estimated_output_tokens` (the assumed output length used for cost estimates). A
**channel** references exactly one prompt by name (`channels.prompt_name`,
validated against the `prompts` table) and carries its own digest recipients
(`channels.notify_emails`, JSON). The prompt is required and drives **both** the
manual estimate flow (`routers/estimates.py` resolves it from the channel — there
is no per-run prompt picker) and the monitor. A prompt can't be deleted while a
channel uses it (`Database.channels_using_prompt` → 409). Prompt names are
immutable (channels reference them by name). On first run, `main.py`
`_bootstrap_prompts` imports any legacy `prompts`/`active_prompt` still in
`config.yaml` (back-filling channels that had no prompt), else seeds one starter
prompt so a fresh install can add a channel right away.

**Structured mentions.** A prompt may declare `entity_kind` (coin, stock,
product…) and its own `stance_labels`; with labels set, summarization switches to
structured output. One call returns `{summary, mentions[]}` — so extraction costs
no extra input tokens — and every mention has the same fixed shape (`entity`,
`stance` from the prompt's labels, `confidence`, `rationale`, `quote`,
`timestamp_seconds`), which is what lets the UI render any prompt's mentions.
Mentions land in the `mentions` table, keyed for grouping by `entity_key`
(whitespace-collapsed, case-folded); `save_summary` replaces a video's mentions in
the same transaction, so reprocessing never duplicates them. Claude is given the
prompt's already-known entity names so the same thing keeps one name across
videos. `ClaudeSummarizer.request_kwargs` builds the request once and both
`estimate` (`count_tokens`) and `summarize` (`messages.stream`) use it — the
estimate must count exactly what gets billed. With extraction on, a `max_tokens`
stop or unparseable JSON is a `SummarizerError`, not a warning: truncated JSON is
unusable. `GET /api/entities` is the per-entity overview (latest stance, the
stance before it, counts), `GET /api/mentions` the timeline.

**Transcripts keep caption timestamps.** `transcripts.fetch_transcript` returns a
`Transcript` (flat `text` plus `segments`), stored as `video_summaries.transcript`
and `transcript_segments` (JSON). Extraction prompts are sent
`render_timestamped(...)` — `[mm:ss]` lines — so quotes can carry a timestamp and
the UI can deep-link with `&t=Ns`; plain prompts still get the flat text, so their
cost is unchanged. Rows saved before this have no segments: they render flat and
their mentions have no timestamp.

**Dates: store/serve UTC, render local.** The backend emits every timestamp as
timezone-aware **UTC ISO 8601** (`youtube_client._utc_iso`, DB `*_at` columns).
The frontend renders in the viewer's locale/timezone via `src/lib/datetime.ts`
(`formatDateTime` / `formatDate` / `formatPublished`). Never format dates
server-side for display, and never render a bare timestamp string in a component.
The **only** exception is the monitor's digest email (`monitor._email_date`):
there is no client to render it, so it formats a readable UTC stamp server-side.

**Process-tab "real dates."** yt-dlp's cheap flat channel listing has **no**
exact dates — only day-level approximations (via the `approximate_date`
extractor arg). Exact publish times are recovered from the channel **RSS feed**
(`youtube_client._fetch_rss_dates`, one request, ~15 newest) and, for processed
videos, from the date already stored in the DB. Anything still approximate is
flagged (`VideoOut.date_approximate`) and shown with a `~`. Getting exact dates
for the whole listing would need one metadata request per video (slow, 429-prone)
— don't do that.

**Layout stability + always-visible scrollbar.** `src/index.css` sets
`overflow-y: scroll` on `<html>` so the vertical scrollbar is always present.
This (a) stops the layout shifting when switching between a tall and short view,
and (b) keeps the scrollbar visible when a Radix overlay opens: Radix locks
scroll by setting `overflow: hidden` on `<body>`, which would remove a
body-owned scrollbar, but the one on `<html>` stays. Radix (`react-remove-scroll`)
also adds a compensating `margin-right` on `body[data-scroll-locked]`; since our
scrollbar never goes away that would shift the page, so
`html body[data-scroll-locked] { margin-right/padding-right: 0 !important }`
neutralizes it. Keep both rules; test dropdown + dialog open for shift and for a
vanishing scrollbar if you touch layout/CSS.

**Reprocessing.** Already-processed videos are selectable in the Process tab
(status flips to "Reprocess"). The estimate endpoint reuses the stored transcript
for known videos (no YouTube request), and `Database.save_summary` upserts
(`ON CONFLICT(video_id) DO UPDATE`), so reprocessing overwrites the old summary.

**YouTube 429s are IP rate-limiting, not bugs.** Requests are paced process-wide
(`youtube_client._throttle`, `youtube_request_interval` in config). Transcript
fetch retries once after a backoff, then skips the rest of the batch to avoid
digging deeper. Don't parallelize YouTube requests.

**The digest email is HTML, and summaries are Markdown.** Claude returns
Markdown, so the monitor runs it through `yt_summarizer/markdown_email.py`
(`render`) instead of escaping it verbatim — otherwise `**bold**` reaches the
inbox as literal asterisks. That module escapes the text **first** and only then
turns the supported constructs back into tags, so raw HTML in model output can
never reach a recipient; keep that ordering if you extend it. Mail clients drop
`<style>` blocks, so every tag it emits carries an inline `style`. Subjects name
the video when a digest holds exactly one (`monitor._build_subject`).

**Jobs & estimates are in-memory.** Only one summarization job runs at a time
(`JobRegistry`). Estimates are stored in memory and consumed on approval
(`EstimateStore`); they expire on server restart (client re-runs the estimate).
What the user approved is exactly what is billed — don't re-fetch transcripts at
job time.

## Don't commit

`.env` (secrets), `videos.db` / any SQLite data, `frontend/dist`, scratch files.
Work on a feature branch; `master` is the default PR base.
