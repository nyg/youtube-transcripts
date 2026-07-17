# YouTube Transcript Summarizer

Summarize the recent videos of a YouTube channel with Claude, straight from your
terminal.

- Lists a channel's recent **uploads and live VODs** (Shorts are excluded) via
  [yt-dlp](https://github.com/yt-dlp/yt-dlp) — **no YouTube API key needed**
- Fetches transcripts with `youtube-transcript-api`
- Shows an **exact input token count** (Anthropic's free `count_tokens`
  endpoint) and a **cost estimate before every API call**, and asks for
  confirmation
- Stores transcript, AI response, token usage and cost in **SQLite** — videos
  are never processed twice
- Generates a responsive, self-contained **HTML report** (dark-mode aware)

## Requirements

- Python 3.14 (3.11+ should work)
- An Anthropic API key ([platform.claude.com](https://platform.claude.com/))

## Setup

```bash
git clone <this repo> && cd youtube-transcripts

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then put your ANTHROPIC_API_KEY in .env
```

Edit `config.yaml` and set the channel you want to follow:

```yaml
channel: "@SomeChannel"   # @handle, UC... channel ID, or full channel URL
```

## Usage

```bash
# Interactive: list unprocessed videos, choose how many to process.
# Each video shows a token count + cost estimate and asks for confirmation.
python main.py

# Process up to 5 newest unprocessed videos (still confirms each API call)
python main.py --max 5

# Fully unattended: no per-video confirmation
python main.py --max 5 --yes

# Only regenerate the HTML report from the database
python main.py --html

# One-off overrides
python main.py --channel "@OtherChannel" --prompt key-takeaways
```

The HTML report is written to `output/summaries.html` (configurable) and is
regenerated automatically after each processing run. Open it in any browser —
latest videos first, dark mode follows your system preference.

## Configuration (`config.yaml`)

| Key | Purpose |
| --- | --- |
| `channel` | `@handle`, `UC...` channel ID, or full channel URL |
| `max_videos_fetch` | How many recent videos/lives to list |
| `transcript_languages` | Preferred transcript languages, in order; falls back to any available |
| `model` | Claude model ID (default `claude-opus-4-8`) |
| `max_output_tokens` | Hard cap on response length |
| `estimated_output_tokens` | Assumed output size for the *pre-call* cost estimate |
| `pricing` | $/1M input & output tokens per model — used for cost math |
| `active_prompt` / `prompts` | Named system prompts; pick one with `active_prompt` or `--prompt` |
| `database` | SQLite file path (default `data/videos.db`) |
| `html_output` | Report path (default `output/summaries.html`) |

Secrets live in `.env` (only `ANTHROPIC_API_KEY`), never in `config.yaml`.

## How it works

1. yt-dlp lists the channel's `/videos` and `/streams` tabs (flat extraction —
   two cheap requests, no API key). Shorts live in a separate tab and are never
   fetched.
2. The list is diffed against the SQLite database, so already-processed videos
   are skipped.
3. For each selected video, the transcript is fetched and the *exact* input
   token count is computed server-side with Anthropic's free `count_tokens`
   endpoint. You see tokens + estimated cost and confirm before anything is
   billed.
4. The transcript is sent to Claude (streaming, so long transcripts don't hit
   HTTP timeouts). Actual token usage and cost are stored with the result.
5. `video_summaries` table: `video_id` (unique), `title`, `url`,
   `published_at`, `transcript`, `prompt_name`, `model`, `ai_response`,
   `tokens_input`, `tokens_output`, `cost_usd`, `processed_at`.

## Troubleshooting

- **"Could not retrieve transcript"** — the video has no transcript (disabled
  by the uploader, or not yet generated for a very recent upload/live). The
  video is skipped; it will show up again as unprocessed on the next run.
- **No videos found / yt-dlp errors** — YouTube changes its site regularly;
  update with `pip install -U yt-dlp`.
- **Anthropic authentication failed** — check that `.env` exists and contains
  a valid `ANTHROPIC_API_KEY`.
- **Costs look wrong** — the `pricing` table in `config.yaml` is only used for
  display; keep it in sync with the official pricing page.
- **Reprocess a video** — delete its row:
  `sqlite3 data/videos.db "DELETE FROM video_summaries WHERE video_id='...'"`.
