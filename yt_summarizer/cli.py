"""CLI orchestration: fetch → select → estimate → confirm → summarize → store."""

from __future__ import annotations

import argparse
import dataclasses
import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.prompt import Confirm, IntPrompt
from rich.table import Table

from . import html_report, transcripts, youtube_client
from .claude_client import ClaudeSummarizer, CostEstimate, SummarizerError, format_cost
from .config import Config, ConfigError, load_config
from .database import Database
from .youtube_client import Video

console = Console()
log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-summarizer",
        description="Summarize recent videos (uploads + lives, no Shorts) of a YouTube channel with Claude.",
    )
    parser.add_argument(
        "--max",
        type=int,
        metavar="N",
        help="process up to N newest unprocessed videos (skips the interactive count prompt)",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="only (re)generate the HTML report from the database, then exit",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip the per-video confirmation before each Claude call",
    )
    parser.add_argument("--channel", help="override the channel from the config (@handle, UC... id or URL)")
    parser.add_argument("--prompt", metavar="NAME", help="prompt from the config's 'prompts' section to use")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="path to the config file (default: config.yaml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=verbose, rich_tracebacks=True)],
    )
    if not verbose:
        for noisy in ("httpx", "httpcore", "urllib3", "anthropic"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    if args.channel:
        cfg = dataclasses.replace(cfg, channel=args.channel)
    if args.prompt:
        if args.prompt not in cfg.prompts:
            raise ConfigError(
                f"--prompt {args.prompt!r} is not defined in the config "
                f"(available: {', '.join(cfg.prompts)})"
            )
        cfg = dataclasses.replace(cfg, active_prompt=args.prompt)
    return cfg


def _generate_report(cfg: Config, db: Database) -> None:
    path = html_report.generate_report(db.all_summaries(), cfg.html_output, cfg.channel)
    console.print(f"[green]HTML report written to[/green] [bold]{path}[/bold]")


def _show_new_videos(videos: list[Video], channel: str) -> None:
    table = Table(title=f"Unprocessed videos — {escape(channel)}", title_justify="left")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Published", style="magenta", no_wrap=True)
    table.add_column("Title")
    for idx, video in enumerate(videos, 1):
        table.add_row(str(idx), video.published_at or "?", escape(video.title))
    console.print(table)


def _ask_count(available: int) -> int:
    while True:
        count = IntPrompt.ask(
            f"How many videos to process (0-{available})", default=0, console=console
        )
        if 0 <= count <= available:
            return count
        console.print(f"[red]Please enter a number between 0 and {available}.[/red]")


def run(args: argparse.Namespace) -> int:
    cfg = _apply_overrides(load_config(args.config), args)
    db = Database(cfg.database)

    if args.html:
        _generate_report(cfg, db)
        return 0

    with console.status(f"Fetching recent videos for {escape(cfg.channel)}..."):
        videos = youtube_client.list_recent_videos(cfg.channel, cfg.max_videos_fetch)
    if not videos:
        console.print(f"[red]No videos found for {escape(cfg.channel)!r} — check the channel name.[/red]")
        return 1

    processed = db.processed_ids()
    new_videos = [v for v in videos if v.video_id not in processed]
    console.print(
        f"Found [bold]{len(videos)}[/bold] recent videos/lives — "
        f"[green]{len(videos) - len(new_videos)}[/green] already processed, "
        f"[yellow]{len(new_videos)}[/yellow] new."
    )
    if not new_videos:
        console.print("Nothing new to process. Use --html to regenerate the report.")
        return 0

    _show_new_videos(new_videos, cfg.channel)

    if args.max is not None:
        count = max(0, min(args.max, len(new_videos)))
    else:
        count = _ask_count(len(new_videos))
    if count == 0:
        console.print("Nothing selected.")
        return 0

    selection = new_videos[:count]  # list is sorted newest first
    summarizer = ClaudeSummarizer(cfg.model, cfg.max_output_tokens, cfg.pricing)
    prompt_text = cfg.prompt_text
    skipped = 0

    # Phase 1 — fetch all transcripts and compute all estimates (nothing billed yet)
    prepared: list[tuple[Video, str, CostEstimate]] = []
    for idx, video in enumerate(selection, 1):
        label = f"\\[{idx}/{len(selection)}] {escape(video.title)}"

        with console.status(f"{label} — fetching metadata..."):
            video = youtube_client.fetch_video_details(video)

        try:
            with console.status(f"{label} — fetching transcript..."):
                transcript = transcripts.fetch_transcript(video.video_id, cfg.transcript_languages)
        except transcripts.TranscriptError as exc:
            log.warning("Skipping video: %s", exc)
            skipped += 1
            continue

        try:
            with console.status(f"{label} — counting tokens..."):
                estimate = summarizer.estimate(prompt_text, transcript, cfg.estimated_output_tokens)
        except SummarizerError as exc:
            # Auth/model problems would fail for every video — stop the batch.
            console.print(f"[red]{escape(str(exc))}[/red]")
            return 1

        prepared.append((video, transcript, estimate))

    if not prepared:
        console.print("[yellow]No transcripts available for the selected videos.[/yellow]")
        return 0

    # Show one combined estimate and ask for a single confirmation
    est_table = Table(title="Cost estimate", title_justify="left")
    est_table.add_column("#", justify="right", style="cyan", no_wrap=True)
    est_table.add_column("Published", style="magenta", no_wrap=True)
    est_table.add_column("Title")
    est_table.add_column("Input tokens", justify="right", no_wrap=True)
    est_table.add_column("Est. cost", justify="right", no_wrap=True)
    total_input = 0
    total_est_cost: float | None = 0.0
    for idx, (video, _transcript, estimate) in enumerate(prepared, 1):
        total_input += estimate.input_tokens
        if estimate.cost_usd is None:
            total_est_cost = None
        elif total_est_cost is not None:
            total_est_cost += estimate.cost_usd
        est_table.add_row(
            str(idx),
            video.published_at or "?",
            escape(video.title),
            f"{estimate.input_tokens:,}",
            f"${estimate.cost_usd:.4f}" if estimate.cost_usd is not None else "n/a",
        )
    est_table.add_section()
    est_table.add_row(
        "",
        "",
        "[bold]Total[/bold]",
        f"[bold]{total_input:,}[/bold]",
        f"[bold]{format_cost(total_est_cost)}[/bold]",
    )
    console.print(est_table)
    console.print(
        f"Model [bold]{cfg.model}[/bold], prompt [bold]{cfg.active_prompt}[/bold], "
        f"assuming ~{cfg.estimated_output_tokens:,} output tokens per video."
    )

    if not args.yes and not Confirm.ask(
        f"Send {len(prepared)} video{'s' if len(prepared) != 1 else ''} to Claude?",
        default=True,
        console=console,
    ):
        console.print("Aborted — nothing was sent to Claude.")
        return 0

    # Phase 2 — summarize and store
    processed_count = 0
    total_cost = 0.0
    for idx, (video, transcript, _estimate) in enumerate(prepared, 1):
        console.rule(f"[bold]\\[{idx}/{len(prepared)}][/bold] {escape(video.title)}")
        try:
            with console.status(f"Summarizing with {cfg.model}..."):
                result = summarizer.summarize(prompt_text, transcript)
        except SummarizerError as exc:
            log.error("Failed to summarize %s: %s", video.video_id, exc)
            skipped += 1
            continue

        db.save_summary(
            video_id=video.video_id,
            title=video.title,
            url=video.url,
            published_at=video.published_at,
            transcript=transcript,
            prompt_name=cfg.active_prompt,
            model=cfg.model,
            ai_response=result.text,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
            cost_usd=result.cost_usd,
        )
        processed_count += 1
        if result.cost_usd is not None:
            total_cost += result.cost_usd
        console.print(
            f"[green]Saved.[/green] Actual usage: {result.tokens_input:,} in / "
            f"{result.tokens_output:,} out — {format_cost(result.cost_usd)}"
        )

    console.rule("Done")
    console.print(
        f"Processed [green]{processed_count}[/green], skipped [yellow]{skipped}[/yellow]. "
        f"Total cost: [bold]${total_cost:.4f}[/bold]"
    )
    if processed_count:
        _generate_report(cfg, db)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return run(args)
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {escape(str(exc))}")
        return 1
    except ValueError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Aborted.[/yellow]")
        return 130
    except EOFError:
        console.print("\n[yellow]Aborted (no input).[/yellow]")
        return 1
