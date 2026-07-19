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
           │   ├── main.py         lifespan wiring: config, db, summarizer, jobs
           │   ├── routers/        channels, estimates, jobs, summaries, meta
           │   ├── jobs.py         in-memory job registry + background worker
           │   ├── estimates.py    in-memory store carrying estimates -> jobs
           │   └── schemas.py      Pydantic API models
           └── yt_summarizer/  domain modules
               ├── config.py       loads config.yaml + .env
               ├── paths.py        XDG resolution for config file & database
               ├── youtube_client.py  yt-dlp listing, RSS date enrichment
               ├── transcripts.py  caption track selection + json3 parsing
               ├── claude_client.py token counting, estimation, summarization
               └── database.py     SQLite persistence
```

The Vite dev server proxies `/api/*` to `http://localhost:8000`, so the browser
only talks to `:5173`.

## Run / test

```bash
make install          # .venv + backend deps + frontend npm install
make backend          # uvicorn --reload on :8000  (run from repo root)
make frontend         # Vite on :5173

# backend tests (pytest is in requirements.txt; install into .venv if missing)
cd backend && ../.venv/bin/python -m pytest -q

# frontend checks
cd frontend && npm run build   # tsc -b + vite build (type-checks)
cd frontend && npm run lint    # oxlint
```

Python 3.14 lives in `.venv`. Backend commands run from `backend/` using
`../.venv/bin/...`. `ANTHROPIC_API_KEY` goes in a `.env` next to the config file
(only needed for actual summarization, not for listing/browsing).

To verify UI changes without touching the user's real DB or hammering YouTube,
run the backend against an isolated `XDG_DATA_HOME`/`XDG_CONFIG_HOME` pointed at
a scratch dir and seed a test `videos.db` (see `yt_summarizer/database.py`).

## Conventions & gotchas (read before touching these areas)

**Paths are XDG-based** (`yt_summarizer/paths.py`). Config resolves from
`$XDG_CONFIG_HOME/yt-summarizer/config.yaml` (bundled `backend/config.yaml` is
the fallback; `$YT_SUMMARIZER_CONFIG` overrides). Database defaults to
`$XDG_DATA_HOME/yt-summarizer/videos.db`. Don't hardcode a repo-relative
database path.

**Dates: store/serve UTC, render local.** The backend emits every timestamp as
timezone-aware **UTC ISO 8601** (`youtube_client._utc_iso`, DB `*_at` columns).
The frontend renders in the viewer's locale/timezone via `src/lib/datetime.ts`
(`formatDateTime` / `formatDate` / `formatPublished`). Never format dates
server-side for display, and never render a bare timestamp string in a component.

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

**Jobs & estimates are in-memory.** Only one summarization job runs at a time
(`JobRegistry`). Estimates are stored in memory and consumed on approval
(`EstimateStore`); they expire on server restart (client re-runs the estimate).
What the user approved is exactly what is billed — don't re-fetch transcripts at
job time.

## Don't commit

`.env` (secrets), `videos.db` / any SQLite data, `frontend/dist`, scratch files.
Work on a feature branch; `master` is the default PR base.
