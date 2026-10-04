"""Settings, the secrets, and the config.yaml an older install still has."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from croniter import croniter
from dotenv import load_dotenv

from . import paths
from .models import BUILT_IN, FAMILIES, family_of

# Top of every hour, in the server's local time.
DEFAULT_SCHEDULE = "0 * * * *"
DEFAULT_MAX_OUTPUT_TOKENS = 8192

_LEGACY_KEYS = (
    "max_videos_fetch",
    "transcript_languages",
    "youtube_request_interval",
    "cookies_file",
    "monitoring",
    "ask",
)


class ConfigError(Exception):
    """Raised when the configuration file or a setting is missing or invalid."""


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1 million tokens."""

    input_per_mtok: float
    output_per_mtok: float


# Prices of the BUILT_IN models; keep both in step.
DEFAULT_PRICING: dict[str, ModelPricing] = {
    "fable": ModelPricing(10.0, 50.0),
    "opus": ModelPricing(4.0, 20.0),
    "sonnet": ModelPricing(2.0, 10.0),
    "haiku": ModelPricing(1.0, 5.0),
}


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
class Settings:
    max_videos_fetch: int
    transcript_languages: tuple[str, ...]
    youtube_request_interval: float
    cookies_file: Path | None
    pricing: dict[str, ModelPricing]  # keyed by model family
    # The model each family's price was last saved for; a family that has moved
    # on to a newer model is flagged so its price gets checked.
    priced_models: dict[str, str]
    monitor: MonitorConfig
    ask: AskConfig


def load_secrets(legacy_config: Path | None) -> None:
    # Secrets live in a .env in the config directory, or next to an older config
    # file kept elsewhere; also fall back to the default search (CWD and parents)
    # so an existing backend/.env keeps working.
    if legacy_config is not None:
        load_dotenv(legacy_config.parent / ".env")
    load_dotenv(paths.config_home() / ".env")
    load_dotenv()


def read_legacy_config(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} does not contain a YAML mapping")
    _reject_relocated_database(path, raw.get("database"))
    return raw


def _reject_relocated_database(config_file: Path, configured: object) -> None:
    if not configured:
        return
    database = Path(str(configured)).expanduser()
    if not database.is_absolute():
        database = paths.data_home() / database
    if database != paths.database_path():
        # Opening the default database instead would look like every summary was lost.
        raise ConfigError(
            f"{config_file} sets 'database: {configured}', which is no longer read: the "
            f"database is always {paths.database_path()}. Move yours there, or point "
            "$XDG_DATA_HOME at the folder holding its yt-summarizer directory, then "
            "remove that line."
        )


def legacy_settings(file_config: Mapping[str, Any]) -> dict:
    settings = {key: file_config[key] for key in _LEGACY_KEYS if file_config.get(key) is not None}
    pricing = file_config.get("pricing")
    if isinstance(pricing, dict):
        # config.yaml priced model ids; only the price of a family's current model carries over.
        settings["pricing"] = {
            family: entry
            for model_id, entry in pricing.items()
            if (family := family_of(str(model_id))) and BUILT_IN[family].id == str(model_id)
        }
    return settings


def parse_settings(raw: Mapping[str, Any]) -> Settings:
    try:
        settings = Settings(
            max_videos_fetch=int(raw.get("max_videos_fetch", 25)),
            transcript_languages=tuple(
                str(lang).strip()
                for lang in raw.get("transcript_languages") or ["en"]
                if str(lang).strip()
            )
            or ("en",),
            youtube_request_interval=float(raw.get("youtube_request_interval", 2.0)),
            cookies_file=(
                Path(str(raw["cookies_file"])).expanduser() if raw.get("cookies_file") else None
            ),
            pricing=_parse_pricing(raw.get("pricing") or {}),
            priced_models=_parse_priced_models(raw.get("priced_models") or {}),
            monitor=_parse_monitor(raw.get("monitoring") or {}),
            ask=_parse_ask(raw.get("ask") or {}),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid setting: {exc}") from exc
    if settings.max_videos_fetch < 1:
        raise ConfigError("max_videos_fetch must be at least 1")
    if settings.youtube_request_interval < 0:
        raise ConfigError("youtube_request_interval cannot be negative")
    return settings


def settings_to_raw(settings: Settings) -> dict:
    monitor = settings.monitor
    ask = settings.ask
    return {
        "max_videos_fetch": settings.max_videos_fetch,
        "transcript_languages": list(settings.transcript_languages),
        "youtube_request_interval": settings.youtube_request_interval,
        "cookies_file": str(settings.cookies_file) if settings.cookies_file else None,
        "pricing": {
            family: {"input": price.input_per_mtok, "output": price.output_per_mtok}
            for family, price in settings.pricing.items()
        },
        "priced_models": dict(settings.priced_models),
        "monitoring": {
            "enabled": monitor.enabled,
            "schedule": monitor.schedule,
            "run_on_start": monitor.run_on_start,
            "max_videos_check": monitor.max_videos_check,
            "max_age_hours": monitor.max_age_hours,
            "daily_budget_usd": monitor.daily_budget_usd,
            "resend_from": monitor.resend_from,
            "subject_prefix": monitor.subject_prefix,
        },
        "ask": {
            "max_context_tokens": ask.max_context_tokens,
            "estimated_output_tokens": ask.estimated_output_tokens,
            "max_output_tokens": ask.max_output_tokens,
        },
    }


def _parse_pricing(raw: object) -> dict[str, ModelPricing]:
    if not isinstance(raw, dict):
        raise ConfigError("'pricing' must be a mapping")
    pricing = dict(DEFAULT_PRICING)
    for family in FAMILIES:
        entry = raw.get(family)
        if entry is None:
            continue
        try:
            price = ModelPricing(
                input_per_mtok=float(entry["input"]),
                output_per_mtok=float(entry["output"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(
                f"Invalid pricing entry for {family!r}: expected "
                "'{input: <$/1M>, output: <$/1M>}'"
            ) from exc
        if price.input_per_mtok < 0 or price.output_per_mtok < 0:
            raise ConfigError(f"The price of {family!r} cannot be negative")
        pricing[family] = price
    return pricing


def _parse_priced_models(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ConfigError("'priced_models' must be a mapping")
    return {family: str(raw.get(family) or BUILT_IN[family].alias) for family in FAMILIES}


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
    if monitor.max_videos_check < 1:
        raise ConfigError("monitoring.max_videos_check must be at least 1")
    if monitor.max_age_hours < 0:
        raise ConfigError("monitoring.max_age_hours cannot be negative")
    if monitor.daily_budget_usd < 0:
        raise ConfigError("monitoring.daily_budget_usd cannot be negative")
    return monitor
