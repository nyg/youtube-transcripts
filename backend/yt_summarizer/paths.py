"""XDG Base Directory resolution for the config file and the database.

Follows the XDG Base Directory Specification so the app stores things where a
Linux user expects (and honours the same env vars on macOS):

  - config:  $XDG_CONFIG_HOME/yt-summarizer/config.yaml
             (default ~/.config/yt-summarizer/config.yaml)
  - data:    $XDG_DATA_HOME/yt-summarizer/videos.db
             (default ~/.local/share/yt-summarizer/videos.db)

For a checkout that has not been configured yet, the config.yaml bundled with
the repository is used as a fallback so the app runs out of the box. An
explicit YT_SUMMARIZER_CONFIG env var overrides everything (handy for tests and
for running several profiles).
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "yt-summarizer"

# config.yaml shipped in the repo (backend/config.yaml), used as a fallback
# template when the user has no XDG config yet.
_BUNDLED_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


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


def config_path() -> Path:
    """Resolve which config.yaml to load.

    Precedence: the YT_SUMMARIZER_CONFIG override, then the XDG config file,
    then the config.yaml bundled with the repository.
    """
    override = os.environ.get("YT_SUMMARIZER_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = config_home() / "config.yaml"
    if xdg.exists():
        return xdg
    return _BUNDLED_CONFIG


def resolve_database_path(configured: str | None) -> Path:
    """Resolve the config's `database:` value to an absolute path.

    Absolute paths are honoured as-is. A relative path or bare filename is
    placed under the XDG data directory; when unset it defaults to
    ``videos.db`` there.
    """
    if configured:
        path = Path(configured).expanduser()
        if path.is_absolute():
            return path
        return data_home() / path
    return data_home() / "videos.db"
