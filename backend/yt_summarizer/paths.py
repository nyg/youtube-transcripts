"""XDG Base Directory resolution for the config file and the database.

Follows the XDG Base Directory Specification so the app stores things where a
Linux user expects (and honours the same env vars on macOS):

  - config:  $XDG_CONFIG_HOME/yt-summarizer/config.yaml
             (default ~/.config/yt-summarizer/config.yaml)
  - data:    $XDG_DATA_HOME/yt-summarizer/videos.db
             (default ~/.local/share/yt-summarizer/videos.db)

The config file is never read out of the checkout: on first run `ensure_config`
copies the bundled `backend/config.example.yaml` template to the XDG location and
loads from there, so editing your settings never dirties a tracked file. An
explicit YT_SUMMARIZER_CONFIG env var overrides everything (handy for tests and
for running several profiles) and never triggers a copy.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

APP_NAME = "yt-summarizer"

log = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent

# The template shipped in the repo, copied to the XDG config dir on first run.
_TEMPLATE_CONFIG = _BACKEND_DIR / "config.example.yaml"

# Older installs kept a live (edited) config.yaml in the checkout. If one is
# still there it holds real settings, so it wins over the template as the seed.
_LEGACY_CONFIG = _BACKEND_DIR / "config.yaml"


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


def _seed_config() -> Path:
    """The file to copy into the XDG config dir on first run."""
    return _LEGACY_CONFIG if _LEGACY_CONFIG.exists() else _TEMPLATE_CONFIG


def ensure_config() -> Path:
    """Resolve the config.yaml to load, creating it from the template if needed.

    Precedence: the YT_SUMMARIZER_CONFIG override (used as-is, never copied),
    then the XDG config file, which is created from the bundled template on
    first run. If that copy fails the template is read in place so the app
    still starts.
    """
    override = os.environ.get("YT_SUMMARIZER_CONFIG")
    if override:
        return Path(override).expanduser()

    target = config_home() / "config.yaml"
    if target.exists():
        return target

    seed = _seed_config()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed, target)
    except OSError as exc:
        log.warning("Could not create %s (%s) — reading %s in place", target, exc, seed)
        return seed
    log.info("Created %s from %s", target, seed)
    return target


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
