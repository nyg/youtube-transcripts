"""Configuration loading: .env for secrets, config.yaml for everything else."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1 million tokens."""

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class Config:
    channel: str
    max_videos_fetch: int
    transcript_languages: tuple[str, ...]
    model: str
    max_output_tokens: int
    estimated_output_tokens: int
    pricing: dict[str, ModelPricing]
    active_prompt: str
    prompts: dict[str, str]
    database: Path
    html_output: Path

    @property
    def prompt_text(self) -> str:
        return self.prompts[self.active_prompt]


def load_config(path: Path) -> Config:
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

    return Config(
        channel=str(raw.get("channel") or "").strip(),
        max_videos_fetch=int(raw.get("max_videos_fetch", 25)),
        transcript_languages=tuple(str(lang) for lang in raw.get("transcript_languages") or ["en"]),
        model=str(raw.get("model", "claude-opus-4-8")),
        max_output_tokens=int(raw.get("max_output_tokens", 8192)),
        estimated_output_tokens=int(raw.get("estimated_output_tokens", 2000)),
        pricing=pricing,
        active_prompt=active_prompt,
        prompts=prompts,
        database=Path(raw.get("database", "data/videos.db")),
        html_output=Path(raw.get("html_output", "output/summaries.html")),
    )
