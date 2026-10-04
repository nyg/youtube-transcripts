"""Configuration loading: .env for secrets, config.yaml for everything else."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from croniter import croniter
from dotenv import load_dotenv

from . import paths

# Top of every hour, in the server's local time.
DEFAULT_SCHEDULE = "0 * * * *"
DEFAULT_MAX_OUTPUT_TOKENS = 8192


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1 million tokens."""

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class MonitorConfig:
    """Settings for the background monitor (see monitor.py)."""

    enabled: bool
    schedule: str  # 5-field cron expression, evaluated in the server's local time
    run_on_start: bool  # also run one catch-up cycle when the server starts
    max_videos_check: int
    max_age_hours: int  # only auto-process videos newer than this; 0 = no limit
    daily_budget_usd: float  # hard cap across all channels; 0 = unlimited
    resend_from: str
    subject_prefix: str


@dataclass(frozen=True)
class AskConfig:
    """Settings for cross-video questions (see analysis.py)."""

    max_context_tokens: int
    estimated_output_tokens: int
    max_output_tokens: int


@dataclass(frozen=True)
class Config:
    max_videos_fetch: int
    transcript_languages: tuple[str, ...]
    youtube_request_interval: float
    cookies_file: Path | None
    pricing: dict[str, ModelPricing]
    database: Path
    monitor: MonitorConfig
    ask: AskConfig


def load_config(path: Path) -> Config:
    # Secrets live in a .env next to the config file; also fall back to the
    # default search (CWD and parents) so an existing backend/.env keeps working.
    load_dotenv(path.parent / ".env")
    load_dotenv()

    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} does not contain a YAML mapping")

    pricing: dict[str, ModelPricing] = {}
    for model_id, entry in (raw.get("pricing") or {}).items():
        try:
            pricing[str(model_id)] = ModelPricing(
                input_per_mtok=float(entry["input"]),
                output_per_mtok=float(entry["output"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(
                f"Invalid pricing entry for {model_id!r}: expected "
                "'{input: <$/1M>, output: <$/1M>}'"
            ) from exc

    monitor = _parse_monitor(raw.get("monitoring") if raw.get("monitoring") is not None else {})
    ask = _parse_ask(raw.get("ask") if raw.get("ask") is not None else {})

    return Config(
        max_videos_fetch=int(raw.get("max_videos_fetch", 25)),
        transcript_languages=tuple(str(lang) for lang in raw.get("transcript_languages") or ["en"]),
        youtube_request_interval=float(raw.get("youtube_request_interval", 2.0)),
        cookies_file=Path(str(raw["cookies_file"])).expanduser() if raw.get("cookies_file") else None,
        pricing=pricing,
        database=paths.resolve_database_path(raw.get("database")),
        monitor=monitor,
        ask=ask,
    )


def _parse_ask(raw: object) -> AskConfig:
    if not isinstance(raw, dict):
        raise ConfigError("'ask' must be a mapping")
    try:
        ask = AskConfig(
            max_context_tokens=int(raw.get("max_context_tokens", 100_000)),
            estimated_output_tokens=int(raw.get("estimated_output_tokens", 1500)),
            max_output_tokens=int(raw.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError("'ask' values must be whole numbers") from exc
    if ask.max_context_tokens < 1000:
        raise ConfigError("ask.max_context_tokens must be at least 1000")
    if ask.estimated_output_tokens < 1:
        raise ConfigError("ask.estimated_output_tokens must be at least 1")
    if ask.max_output_tokens < 1:
        raise ConfigError("ask.max_output_tokens must be at least 1")
    return ask


def _parse_monitor(raw: object) -> MonitorConfig:
    if not isinstance(raw, dict):
        raise ConfigError("'monitoring' must be a mapping")
    if "interval_minutes" in raw and "schedule" not in raw:
        # Fail loudly rather than silently changing someone's cadence.
        raise ConfigError(
            "monitoring.interval_minutes was replaced by monitoring.schedule, a cron "
            "expression in local time — e.g. interval_minutes: 60 becomes "
            'schedule: "0 * * * *"'
        )
    schedule = str(raw.get("schedule") or DEFAULT_SCHEDULE).strip()
    if not croniter.is_valid(schedule):
        raise ConfigError(f"monitoring.schedule is not a valid cron expression: {schedule!r}")
    monitor = MonitorConfig(
        enabled=bool(raw.get("enabled", False)),
        schedule=schedule,
        run_on_start=bool(raw.get("run_on_start", True)),
        max_videos_check=int(raw.get("max_videos_check", 5)),
        max_age_hours=int(raw.get("max_age_hours", 48)),
        daily_budget_usd=float(raw.get("daily_budget_usd", 1.0)),
        resend_from=str(raw.get("resend_from") or "").strip(),
        subject_prefix=str(raw.get("subject_prefix") or "New video summaries").strip(),
    )
    if monitor.enabled and not monitor.resend_from:
        raise ConfigError("monitoring.resend_from is required when monitoring is enabled")
    return monitor
