"""Configuration loading: .env for secrets, config.yaml for everything else."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import paths


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1 million tokens."""

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class MonitorConfig:
    """Settings for the hourly background monitor (see monitor.py)."""

    enabled: bool
    interval_minutes: int
    max_videos_check: int
    max_age_hours: int  # only auto-process videos newer than this; 0 = no limit
    daily_budget_usd: float  # hard cap across all channels; 0 = unlimited
    resend_from: str
    notify_emails: tuple[str, ...]
    subject_prefix: str


@dataclass(frozen=True)
class Config:
    channel: str
    max_videos_fetch: int
    transcript_languages: tuple[str, ...]
    youtube_request_interval: float
    cookies_file: Path | None
    model: str
    max_output_tokens: int
    estimated_output_tokens: int
    pricing: dict[str, ModelPricing]
    active_prompt: str
    prompts: dict[str, str]
    database: Path
    monitor: MonitorConfig

    @property
    def prompt_text(self) -> str:
        return self.prompts[self.active_prompt]


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

    prompts = {str(name): str(text).strip() for name, text in (raw.get("prompts") or {}).items()}
    if not prompts:
        raise ConfigError("config must define at least one entry under 'prompts'")

    active_prompt = str(raw.get("active_prompt") or next(iter(prompts)))
    if active_prompt not in prompts:
        raise ConfigError(
            f"active_prompt {active_prompt!r} is not defined under 'prompts' "
            f"(available: {', '.join(prompts)})"
        )

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

    return Config(
        channel=str(raw.get("channel") or "").strip(),
        max_videos_fetch=int(raw.get("max_videos_fetch", 25)),
        transcript_languages=tuple(str(lang) for lang in raw.get("transcript_languages") or ["en"]),
        youtube_request_interval=float(raw.get("youtube_request_interval", 2.0)),
        cookies_file=Path(str(raw["cookies_file"])).expanduser() if raw.get("cookies_file") else None,
        model=str(raw.get("model", "claude-opus-4-8")),
        max_output_tokens=int(raw.get("max_output_tokens", 8192)),
        estimated_output_tokens=int(raw.get("estimated_output_tokens", 2000)),
        pricing=pricing,
        active_prompt=active_prompt,
        prompts=prompts,
        database=paths.resolve_database_path(raw.get("database")),
        monitor=monitor,
    )


def _parse_monitor(raw: object) -> MonitorConfig:
    if not isinstance(raw, dict):
        raise ConfigError("'monitoring' must be a mapping")
    emails = tuple(str(e).strip() for e in (raw.get("notify_emails") or []) if str(e).strip())
    monitor = MonitorConfig(
        enabled=bool(raw.get("enabled", False)),
        interval_minutes=int(raw.get("interval_minutes", 60)),
        max_videos_check=int(raw.get("max_videos_check", 5)),
        max_age_hours=int(raw.get("max_age_hours", 48)),
        daily_budget_usd=float(raw.get("daily_budget_usd", 1.0)),
        resend_from=str(raw.get("resend_from") or "").strip(),
        notify_emails=emails,
        subject_prefix=str(raw.get("subject_prefix") or "New video summaries").strip(),
    )
    if monitor.enabled:
        if monitor.interval_minutes < 1:
            raise ConfigError("monitoring.interval_minutes must be at least 1")
        if not monitor.resend_from:
            raise ConfigError("monitoring.resend_from is required when monitoring is enabled")
        if not monitor.notify_emails:
            raise ConfigError(
                "monitoring.notify_emails must list at least one address when monitoring is enabled"
            )
    return monitor
