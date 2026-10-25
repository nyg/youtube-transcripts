"""XDG Base Directory resolution for the database and the secrets.

Follows the XDG Base Directory Specification so the app stores things where a
Linux user expects (and honours the same env vars on macOS):

  - data:    $XDG_DATA_HOME/yt-summarizer/videos.db
             (default ~/.local/share/yt-summarizer/videos.db)
  - secrets: $XDG_CONFIG_HOME/yt-summarizer/.env
             (default ~/.config/yt-summarizer/.env)

There is no config file: settings live in the database. An install from before
that still has a config.yaml in the config directory (or wherever
YT_SUMMARIZER_CONFIG points); `legacy_config` finds it so it can be imported.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "yt-summarizer"


def _xdg_base(env_var: str, default: Path) -> Path:
    raw = os.environ.get(env_var)
    base = Path(raw).expanduser() if raw else default
    return base / APP_NAME


def config_home() -> Path:
    """The app's XDG config directory (~/.config/yt-summarizer by default)."""
    return _xdg_base("XDG_CONFIG_HOME", Path.home() / ".config")


def data_home() -> Path:
    """The app's XDG data directory (~/.local/share/yt-summarizer by default)."""
    return _xdg_base("XDG_DATA_HOME", Path.home() / ".local" / "share")


def database_path() -> Path:
    return data_home() / "videos.db"


def legacy_config() -> Path | None:
    override = os.environ.get("YT_SUMMARIZER_CONFIG")
    path = Path(override).expanduser() if override else config_home() / "config.yaml"
    return path if path.exists() else None
