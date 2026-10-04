"""XDG resolution for the database, and finding an older install's config file."""

from __future__ import annotations

import pytest

from yt_summarizer import paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "YT_SUMMARIZER_CONFIG"):
        monkeypatch.delenv(var, raising=False)


def test_database_lives_in_the_xdg_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.database_path() == tmp_path / "yt-summarizer" / "videos.db"


def test_database_defaults_to_the_home_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    assert paths.database_path() == (
        tmp_path / ".local" / "share" / "yt-summarizer" / "videos.db"
    )


def test_no_config_file_is_needed_or_created(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    found = paths.legacy_config()

    assert found is None
    assert list(tmp_path.iterdir()) == []


def test_an_older_config_file_is_found_in_the_xdg_config_dir(monkeypatch, tmp_path):
    xdg = tmp_path / "yt-summarizer"
    xdg.mkdir(parents=True)
    (xdg / "config.yaml").write_text("max_videos_fetch: 10\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert paths.legacy_config() == xdg / "config.yaml"


def test_config_override_points_at_the_older_file(monkeypatch, tmp_path):
    override = tmp_path / "custom.yaml"
    override.write_text("max_videos_fetch: 10\n", encoding="utf-8")
    monkeypatch.setenv("YT_SUMMARIZER_CONFIG", str(override))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    assert paths.legacy_config() == override


def test_config_override_to_a_missing_file_finds_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("YT_SUMMARIZER_CONFIG", str(tmp_path / "missing.yaml"))

    assert paths.legacy_config() is None
