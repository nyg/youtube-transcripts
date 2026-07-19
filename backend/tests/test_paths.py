"""XDG resolution for the config file and the database."""

from __future__ import annotations

import pytest

from yt_summarizer import paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "YT_SUMMARIZER_CONFIG"):
        monkeypatch.delenv(var, raising=False)


# --- resolve_database_path --------------------------------------------------


def test_database_defaults_to_xdg_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.resolve_database_path(None) == tmp_path / "yt-summarizer" / "videos.db"


def test_database_relative_path_lands_under_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.resolve_database_path("sub/db.sqlite") == (
        tmp_path / "yt-summarizer" / "sub" / "db.sqlite"
    )


def test_database_absolute_path_is_honoured(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    absolute = tmp_path / "elsewhere" / "videos.db"
    assert paths.resolve_database_path(str(absolute)) == absolute


# --- config_path ------------------------------------------------------------


def test_config_override_wins(monkeypatch, tmp_path):
    override = tmp_path / "custom.yaml"
    monkeypatch.setenv("YT_SUMMARIZER_CONFIG", str(override))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert paths.config_path() == override


def test_config_prefers_existing_xdg_file(monkeypatch, tmp_path):
    xdg = tmp_path / "yt-summarizer"
    xdg.mkdir(parents=True)
    (xdg / "config.yaml").write_text("channel: '@x'\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.config_path() == xdg / "config.yaml"


def test_config_falls_back_to_bundled(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # no config there
    result = paths.config_path()
    assert result.name == "config.yaml"
    assert result.parent.name == "backend"


# --- migrate_legacy_database ------------------------------------------------


def test_migration_copies_legacy_when_target_missing(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy" / "videos.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"sqlite-bytes")
    monkeypatch.setattr(paths, "_LEGACY_DATABASE", legacy)

    target = tmp_path / "xdg" / "videos.db"
    assert paths.migrate_legacy_database(target) is True
    assert target.read_bytes() == b"sqlite-bytes"
    assert legacy.exists()  # original left untouched


def test_migration_skipped_when_target_exists(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.db"
    legacy.write_bytes(b"old")
    monkeypatch.setattr(paths, "_LEGACY_DATABASE", legacy)

    target = tmp_path / "videos.db"
    target.write_bytes(b"current")
    assert paths.migrate_legacy_database(target) is False
    assert target.read_bytes() == b"current"


def test_migration_skipped_when_no_legacy(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_LEGACY_DATABASE", tmp_path / "does-not-exist.db")
    assert paths.migrate_legacy_database(tmp_path / "videos.db") is False
