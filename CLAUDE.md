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
           │   ├── main.py         lifespan wiring: config, db, settings, prompt bootstrap, jobs
           │   ├── routers/        channels, prompts, estimates, jobs, summaries,
           │   │                   mentions, search, questions, settings, meta
           │   ├── settings.py     loads the stored settings, holds the current ones
           │   ├── jobs.py         in-memory job registry + background worker
           │   ├── estimates.py    in-memory store carrying estimates -> jobs
           │   ├── prompts.py      resolves a prompt row -> Extraction spec
           │   └── schemas.py      Pydantic API models
           └── yt_summarizer/  domain modules
               ├── config.py       settings parsing/validation, .env, older config.yaml
               ├── models.py       model families, newest model per family (Models API)
               ├── paths.py        XDG resolution for the database & secrets
               ├── youtube_client.py  yt-dlp listing, RSS date enrichment
               ├── transcripts.py  caption track selection + json3 parsing (timed)
               ├── mentions.py     the Mention record + entity_key normalization
               ├── chunking.py     search chunks + FTS5 query escaping
               ├── analysis.py     context assembly for cross-video questions
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
`../.venv/bin/...`. `ANTHROPIC_API_KEY` goes in `$XDG_CONFIG_HOME/yt-summarizer/.env`
(only needed for actual summarization, not for listing/browsing).

To verify UI changes without touching the user's real DB or hammering YouTube,
run the backend against an isolated `XDG_DATA_HOME`/`XDG_CONFIG_HOME` pointed at
a scratch dir and seed a test `videos.db` (see `yt_summarizer/database.py`).

## Conventions & gotchas (read before touching these areas)

**Paths are XDG-based, and there is no config file** (`yt_summarizer/paths.py`).
The database is always `$XDG_DATA_HOME/yt-summarizer/videos.db`
(`paths.database_path()`), secrets are read from
`$XDG_CONFIG_HOME/yt-summarizer/.env`, and everything else is a setting stored
in the database (see below). Nothing creates or requires a `config.yaml`. One
left by an older install (in the config dir, or where `$YT_SUMMARIZER_CONFIG`
points) is only read to import its settings and prompts on the first start;
`config.read_legacy_config` refuses to start if it names another `database`,
because silently opening the default one would look like data loss.
The Makefile's detached-mode logs and PID files go to `$XDG_STATE_HOME/yt-summarizer`
(`STATE_DIR`; not `$XDG_RUNTIME_DIR`, which is wiped when the user's last
session ends — `make start` is meant to survive logout). Nothing the app or the
Makefile writes belongs inside the checkout: don't hardcode a repo-relative
database, config, or log path.

**Settings live in the DB and are edited in the UI.** The `settings` table holds one JSON value per top-level key (`max_videos_fetch`, `transcript_languages`, `youtube_request_interval`, `cookies_file`, `pricing`, `priced_models`, `monitoring`, `ask`). `config.parse_settings` is the single place they are validated, for the stored values and for `PUT /api/settings` alike (a `ConfigError` becomes a 422). On the first start with an empty table, `app/settings.py` `load_settings` imports whatever an older `config.yaml` still holds (`config.legacy_settings`), then the file is ignored. `app.state.settings` is a `SettingsStore`: read `.current` at the time of use and never keep a copy, so a save takes effect without a restart. Saving also re-applies the YouTube pacing and wakes the monitor. Add a setting in `Settings`, `parse_settings`, `settings_to_raw`, `SettingsBody` and the field lists of `SettingsDialog.tsx`.

**The monitor is cron-scheduled in local time.** `monitoring.schedule` is a
5-field cron expression (croniter); `app/monitor.py` recomputes the next fire
time each iteration off `datetime.now().astimezone()`, so timing is wall-clock
stable and restart-independent. This is the one place local time is
authoritative — see the UTC rule below, which governs stored/served timestamps.
`monitoring.run_on_start` (default true) additionally runs one catch-up cycle at
startup. The legacy `interval_minutes` key is rejected with a `ConfigError`
rather than silently ignored. The monitor thread always runs: it idles while
`monitoring.enabled` is false, and `ChannelMonitor.refresh()` wakes it after a
settings save so it re-reads the schedule (enabling it at runtime does not
trigger the catch-up cycle).

**Channels and prompts live in the DB, not config.** Both are UI-managed CRUD
entities (`channels` and `prompts` tables; `routers/channels.py` /
`routers/prompts.py`; React `ChannelManagerDialog` / `PromptManagerDialog`).
A **prompt** carries its own text, model settings and
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

**A prompt chooses a model family, not a model.** The choice is one of `models.FAMILIES` (fable, opus, sonnet, haiku) and always runs on the newest model of that family, so a new model needs no code or settings change. `ModelCatalog` asks the Models API for the list (free, cached for hours), keeps the highest version per family, and falls back to `models.BUILT_IN` while the API is unreachable or for a family it does not list. `prompts.model` therefore stores a family; `main.py` `_adopt_model_families` converts model ids stored by older versions. `video_summaries.model` and `questions.model` keep the concrete model id that ran. The family is resolved to a model when the estimate is made (`app/prompts.py` `model_settings`), never at job time.

**Model family, effort and output cap are per prompt, with no default.** There is no global model. `prompts.model` and `prompts.effort` are nullable so rows from before they existed survive the migration, and because a model may take no effort at all (Haiku 4.5: `ClaudeModel.efforts` is empty). `model_settings` returns `None` when the family is unknown or when the model takes an effort and the prompt has none it accepts, which the estimate router turns into a 422 and the monitor into a skipped channel. The starter and legacy-imported prompts are seeded without a model. Never fall back to a default model or effort. `effort` is sent as `output_config.effort` only when the model takes one. `max_output_tokens` caps thinking plus response and is also the worst case of the monitor's budget pre-check. Model id, effort, cap and price travel together as `ModelSettings`, held in `PreparedEstimate` / `PreparedQuestion`, so a job bills the settings the estimate was approved with even if the prompt or the prices are edited in between. Ask has no prompt: the family and effort come with each question, and `ask.max_output_tokens` is its cap.

**Prices are a setting, per family.** The Models API reports no prices, so `pricing` is edited in Settings (defaults: `config.DEFAULT_PRICING`, which must match `models.BUILT_IN`). Every family always has a price, so a cost is never unknown for a new run (`cost_usd` is still NULL on old rows). `priced_models` records the model each price was saved for; when a family moves to a newer model, `GET /api/meta` reports `price_confirmed: false` and the UI asks to check the price (`PriceNotice.tsx`). Saving the settings confirms the prices for the current models. Until then the old price keeps being used, for estimates and for the monitor's budget.

**Run stats are stored with each summary.** `save_summary` records how the summary was produced: `effort`, `max_output_tokens`, `estimated_output_tokens`, `tokens_thinking`, `stop_reason` and `duration_ms`. `tokens_thinking` comes from `usage.output_tokens_details` and is a part of `tokens_output`, not an addition to it; it is NULL when the API omits the breakdown. `effort` is also NULL for a model that takes none. All six are NULL on rows saved before they existed, they are replaced on reprocess, and the card's "Show stats" (`SummaryStats.tsx`) only appears when `max_output_tokens` is set.

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

**Search is SQLite FTS5, and the index is derived state.** `chunks` is a plain
FTS5 virtual table (no external-content triggers) holding ~60-second transcript
windows plus one chunk per summary; `video_id`, `kind` and `start_seconds` are
UNINDEXED columns. `save_summary` rebuilds a video's chunks in its transaction and
`delete_summary` drops them, so the index never drifts from the summaries.
`Database.backfill_chunks()` runs in the app lifespan and indexes rows that have
no chunks yet — local, free and idempotent, which is how older installs get
search. User input never reaches `MATCH` raw: `chunking.fts_query` keeps
`"phrases"`, quotes every other token and prefix-matches the last one, so FTS5
operators and punctuation are inert. Hits come back with `snippet()` highlights
delimited by \x02/\x03 — control characters, not HTML, so the client marks them
without `dangerouslySetInnerHTML`.

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
(`youtube_client._throttle`, `youtube_request_interval` in Settings). Transcript
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

**Ask reuses the estimate-then-approve contract.** `analysis.build_context`
assembles numbered sources from the DB alone (no API call): mentions in range
first, then summaries up to 60% of the remaining budget, then FTS transcript
excerpts for the question's terms (question words are dropped by
`analysis.search_terms`, and the excerpt query runs in OR mode). The budget is
`ask.max_context_tokens`, approximated at 4 characters per token. The estimate
counts that exact request, the prepared context is held in a second
`EstimateStore` (now generic) and consumed on approval, so the approved cost is
what is billed and a stale id is a 410, as with video jobs. Answers are stored
in `questions` with their sources, and **`spend_since` sums `video_summaries`
and `questions`**, so asking counts toward the monitor's daily budget. The
answer cites sources as `[n]`; the client rewrites those into links, so keep the
marker format if you change the prompt.

**Jobs & estimates are in-memory.** Only one summarization job runs at a time
(`JobRegistry`). Estimates are stored in memory and consumed on approval
(`EstimateStore`); they expire on server restart (client re-runs the estimate).
What the user approved is exactly what is billed — don't re-fetch transcripts at
job time.

## Don't commit

`.env` (secrets), `videos.db` / any SQLite data, `frontend/dist`, scratch files.
Work on a feature branch; `master` is the default PR base.
