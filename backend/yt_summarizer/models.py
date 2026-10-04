from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, get_args

log = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS: tuple[str, ...] = get_args(Effort)

FAMILIES: tuple[str, ...] = ("fable", "opus", "sonnet", "haiku")

_DATE_SUFFIX = re.compile(r"-\d{8}$")

_REFRESH_SECONDS = 6 * 3600
_RETRY_SECONDS = 600


@dataclass(frozen=True)
class ClaudeModel:
    family: str
    id: str
    name: str
    efforts: tuple[str, ...]  # empty when the model rejects an effort level

    @property
    def alias(self) -> str:
        return _DATE_SUFFIX.sub("", self.id)


# Used until the Models API answers, and for a family it does not list.
BUILT_IN: dict[str, ClaudeModel] = {
    model.family: model
    for model in (
        ClaudeModel("fable", "claude-fable-5-1", "Claude Fable 5.1", EFFORT_LEVELS),
        ClaudeModel("opus", "claude-opus-5-5", "Claude Opus 5.5", EFFORT_LEVELS),
        ClaudeModel("sonnet", "claude-sonnet-5-5", "Claude Sonnet 5.5", EFFORT_LEVELS),
        ClaudeModel("haiku", "claude-haiku-4-5", "Claude Haiku 4.5", ()),
    )
}


def family_of(model_id: str) -> str | None:
    parts = model_id.split("-")
    if parts[0] != "claude":
        return None
    return next((part for part in parts[1:] if part in FAMILIES), None)


def _version(model: ClaudeModel) -> tuple[int, ...]:
    return tuple(int(part) for part in model.alias.split("-") if part.isdigit())


def latest_per_family(models: Iterable[ClaudeModel]) -> dict[str, ClaudeModel]:
    latest: dict[str, ClaudeModel] = {}
    for model in models:
        current = latest.get(model.family)
        # On a version tie the alias wins over its dated snapshot.
        if current is None or (_version(model), -len(model.id)) > (
            _version(current),
            -len(current.id),
        ):
            latest[model.family] = model
    return latest


class ModelCatalog:
    def __init__(self, fetch: Callable[[], Iterable[ClaudeModel]]) -> None:
        self._fetch = fetch
        self._lock = threading.Lock()
        self._models = dict(BUILT_IN)
        self._expires_at = 0.0

    def models(self) -> list[ClaudeModel]:
        with self._lock:
            if time.monotonic() >= self._expires_at:
                try:
                    self._load()
                except Exception as exc:
                    log.warning("Could not list Claude models (%s) — keeping the known ones", exc)
                    self._expires_at = time.monotonic() + _RETRY_SECONDS
            return [self._models[family] for family in FAMILIES]

    def resolve(self, family: str) -> ClaudeModel | None:
        return next((model for model in self.models() if model.family == family), None)

    def refresh(self) -> list[ClaudeModel]:
        with self._lock:
            self._load()
        return self.models()

    def _load(self) -> None:
        self._models = {**BUILT_IN, **latest_per_family(self._fetch())}
        self._expires_at = time.monotonic() + _REFRESH_SECONDS
