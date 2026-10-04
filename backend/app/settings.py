from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from yt_summarizer.config import Settings, legacy_settings, parse_settings, settings_to_raw
from yt_summarizer.database import Database

log = logging.getLogger(__name__)


def load_settings(db: Database, file_config: Mapping[str, Any]) -> Settings:
    stored = db.get_settings()
    if stored:
        return parse_settings(stored)
    settings = parse_settings(legacy_settings(file_config))
    db.save_settings(settings_to_raw(settings))
    log.info("Stored the settings in the database — edit them in Settings from now on")
    return settings


class SettingsStore:
    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._current = settings

    @property
    def current(self) -> Settings:
        return self._current

    def replace(self, settings: Settings) -> None:
        self._db.save_settings(settings_to_raw(settings))
        self._current = settings
