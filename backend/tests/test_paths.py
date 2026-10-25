"""XDG resolution for the database, and finding an older install's config file."""

from __future__ import annotations

import pytest

from youtube_transcripts import paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "YOUTUBE_TRANSCRIPTS_CONFIG"):
        monkeypatch.delenv(var, raising=False)


def test_database_lives_in_the_xdg_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.database_path() == tmp_path / "youtube-transcripts" / "videos.db"


def test_database_defaults_to_the_home_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    assert paths.database_path() == (
        tmp_path / ".local" / "share" / "youtube-transcripts" / "videos.db"
    )


def test_no_config_file_is_needed_or_created(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    found = paths.legacy_config()

    assert found is None
    assert list(tmp_path.iterdir()) == []


def test_an_older_config_file_is_found_in_the_xdg_config_dir(monkeypatch, tmp_path):
    xdg = tmp_path / "youtube-transcripts"
    xdg.mkdir(parents=True)
    (xdg / "config.yaml").write_text("max_videos_fetch: 10\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert paths.legacy_config() == xdg / "config.yaml"


def test_config_override_points_at_the_older_file(monkeypatch, tmp_path):
    override = tmp_path / "custom.yaml"
    override.write_text("max_videos_fetch: 10\n", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_TRANSCRIPTS_CONFIG", str(override))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    assert paths.legacy_config() == override


def test_config_override_to_a_missing_file_finds_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_TRANSCRIPTS_CONFIG", str(tmp_path / "missing.yaml"))

    assert paths.legacy_config() is None


def test_the_former_app_dirs_are_moved_to_the_new_name(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / "config" / "yt-summarizer").mkdir(parents=True)
    (tmp_path / "config" / "yt-summarizer" / ".env").write_text("KEY=1\n", encoding="utf-8")
    (tmp_path / "data" / "yt-summarizer").mkdir(parents=True)
    (tmp_path / "data" / "yt-summarizer" / "videos.db").write_bytes(b"db")

    paths.adopt_former_dirs()

    assert (paths.config_home() / ".env").read_text(encoding="utf-8") == "KEY=1\n"
    assert paths.database_path().read_bytes() == b"db"
    assert not (tmp_path / "config" / "yt-summarizer").exists()
    assert not (tmp_path / "data" / "yt-summarizer").exists()


def test_an_existing_app_dir_is_never_replaced_by_the_former_one(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    (tmp_path / "yt-summarizer").mkdir()
    (tmp_path / "yt-summarizer" / "videos.db").write_bytes(b"old")
    paths.data_home().mkdir()
    paths.database_path().write_bytes(b"new")

    paths.adopt_former_dirs()

    assert paths.database_path().read_bytes() == b"new"
    assert (tmp_path / "yt-summarizer" / "videos.db").read_bytes() == b"old"


def test_nothing_is_created_without_former_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    paths.adopt_former_dirs()

    assert list(tmp_path.iterdir()) == []
