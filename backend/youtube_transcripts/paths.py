"""XDG Base Directory resolution for the database and the secrets.

Follows the XDG Base Directory Specification so the app stores things where a
Linux user expects (and honours the same env vars on macOS):

  - data:    $XDG_DATA_HOME/youtube-transcripts/videos.db
             (default ~/.local/share/youtube-transcripts/videos.db)
  - secrets: $XDG_CONFIG_HOME/youtube-transcripts/.env
             (default ~/.config/youtube-transcripts/.env)

There is no config file: settings live in the database. An install from before
that still has a config.yaml in the config directory (or wherever
YOUTUBE_TRANSCRIPTS_CONFIG points); `legacy_config` finds it so it can be imported.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

APP_NAME = "youtube-transcripts"
FORMER_APP_NAME = "yt-summarizer"

log = logging.getLogger(__name__)


def _xdg_root(env_var: str, default: Path) -> Path:
    raw = os.environ.get(env_var)
    return Path(raw).expanduser() if raw else default


def _config_root() -> Path:
    return _xdg_root("XDG_CONFIG_HOME", Path.home() / ".config")


def _data_root() -> Path:
    return _xdg_root("XDG_DATA_HOME", Path.home() / ".local" / "share")


def config_home() -> Path:
    """The app's XDG config directory (~/.config/youtube-transcripts by default)."""
    return _config_root() / APP_NAME


def data_home() -> Path:
    """The app's XDG data directory (~/.local/share/youtube-transcripts by default)."""
    return _data_root() / APP_NAME


def adopt_former_dirs() -> None:
    for root in (_config_root(), _data_root()):
        former, current = root / FORMER_APP_NAME, root / APP_NAME
        if not former.is_dir():
            continue
        if current.exists():
            log.warning("%s is not used: %s already exists", former, current)
            continue
        former.rename(current)
        log.info("Moved %s to %s", former, current)


def database_path() -> Path:
    return data_home() / "videos.db"


def legacy_config() -> Path | None:
    override = os.environ.get("YOUTUBE_TRANSCRIPTS_CONFIG")
    path = Path(override).expanduser() if override else config_home() / "config.yaml"
    return path if path.exists() else None
