"""Model families: the newest model of each is the one on offer."""

from __future__ import annotations

import pytest

from yt_summarizer import models
from yt_summarizer.models import (
    BUILT_IN,
    EFFORT_LEVELS,
    ClaudeModel,
    ModelCatalog,
    family_of,
    latest_per_family,
)


def _model(model_id: str) -> ClaudeModel:
    return ClaudeModel(family_of(model_id) or "", model_id, model_id, EFFORT_LEVELS)


@pytest.mark.parametrize(
    "model_id,family",
    [
        ("claude-opus-5-5", "opus"),
        ("claude-haiku-4-5-20251001", "haiku"),
        ("claude-3-5-sonnet-20241022", "sonnet"),
        ("claude-fable-5-1", "fable"),
        ("claude-mythos-5-1", None),
        ("gpt-5-opus", None),
    ],
)
def test_family_is_read_from_the_model_id(model_id, family):
    assert family_of(model_id) == family


def test_alias_drops_the_snapshot_date():
    assert _model("claude-haiku-4-5-20251001").alias == "claude-haiku-4-5"
    assert _model("claude-opus-5-5").alias == "claude-opus-5-5"


def test_latest_is_the_highest_version_not_the_last_listed():
    listed = [
        _model("claude-opus-5-5"),
        _model("claude-opus-5"),
        _model("claude-opus-4-8"),
        _model("claude-opus-4-1-20250805"),
        _model("claude-sonnet-4-20250514"),
        _model("claude-3-7-sonnet-20250219"),
        _model("claude-sonnet-10"),
        _model("claude-sonnet-9-5"),
    ]

    latest = latest_per_family(listed)

    assert {family: model.id for family, model in latest.items()} == {
        "opus": "claude-opus-5-5",
        "sonnet": "claude-sonnet-10",
    }


def test_alias_wins_over_its_dated_snapshot():
    listed = [_model("claude-haiku-4-5-20251001"), _model("claude-haiku-4-5")]

    assert latest_per_family(listed)["haiku"].id == "claude-haiku-4-5"
    assert latest_per_family(reversed(listed))["haiku"].id == "claude-haiku-4-5"


def test_catalog_offers_one_model_per_family_filling_gaps_with_the_built_in_ones():
    catalog = ModelCatalog(lambda: [_model("claude-opus-6"), _model("claude-opus-5-5")])

    offered = catalog.models()

    assert [model.family for model in offered] == ["fable", "opus", "sonnet", "haiku"]
    assert catalog.resolve("opus").id == "claude-opus-6"
    assert catalog.resolve("haiku") == BUILT_IN["haiku"]
    assert catalog.resolve("gpt") is None


def test_catalog_asks_once_until_the_listing_expires(monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(models.time, "monotonic", lambda: clock[0])
    catalog = ModelCatalog(lambda: calls.append(1) or [])

    catalog.models()
    catalog.models()
    clock[0] += 7 * 3600
    catalog.models()

    assert len(calls) == 2


def test_catalog_keeps_the_known_models_when_listing_fails(monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(models.time, "monotonic", lambda: clock[0])

    def failing():
        calls.append(1)
        raise RuntimeError("offline")

    catalog = ModelCatalog(failing)

    offered = catalog.models()
    catalog.models()
    clock[0] += 601
    catalog.models()

    assert offered == list(BUILT_IN.values())
    assert len(calls) == 2


def test_refresh_lists_again_and_lets_a_failure_through():
    listed = [[_model("claude-opus-6")], [_model("claude-opus-7")]]
    catalog = ModelCatalog(lambda: listed.pop(0))

    first = catalog.resolve("opus").id
    refreshed = catalog.refresh()

    assert (first, refreshed[1].id) == ("claude-opus-6", "claude-opus-7")
    with pytest.raises(IndexError):
        catalog.refresh()
    assert catalog.resolve("opus").id == "claude-opus-7"
