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


# --- ensure_config ----------------------------------------------------------


def test_config_override_wins_without_copying(monkeypatch, tmp_path):
    override = tmp_path / "custom.yaml"
    xdg = tmp_path / "cfg"
    monkeypatch.setenv("YT_SUMMARIZER_CONFIG", str(override))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert paths.ensure_config() == override
    # An explicit override must stay side-effect free.
    assert not xdg.exists()


def test_config_prefers_existing_xdg_file(monkeypatch, tmp_path):
    xdg = tmp_path / "yt-summarizer"
    xdg.mkdir(parents=True)
    (xdg / "config.yaml").write_text("model: mine\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert paths.ensure_config() == xdg / "config.yaml"
    # Never overwrite what the user already configured.
    assert (xdg / "config.yaml").read_text(encoding="utf-8") == "model: mine\n"


def test_config_is_created_from_template(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # nothing there yet
    monkeypatch.setattr(paths, "_LEGACY_CONFIG", tmp_path / "absent.yaml")

    created = paths.ensure_config()

    assert created == tmp_path / "yt-summarizer" / "config.yaml"
    assert created.read_text(encoding="utf-8") == paths._TEMPLATE_CONFIG.read_text(
        encoding="utf-8"
    )


def test_leftover_checkout_config_seeds_the_copy(monkeypatch, tmp_path):
    """An older install's edited backend/config.yaml carries real settings."""
    legacy = tmp_path / "legacy.yaml"
    legacy.write_text("model: from-checkout\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(paths, "_LEGACY_CONFIG", legacy)

    created = paths.ensure_config()

    assert created.read_text(encoding="utf-8") == "model: from-checkout\n"


def test_config_falls_back_to_template_when_copy_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(paths, "_LEGACY_CONFIG", tmp_path / "absent.yaml")

    def _boom(*args, **kwargs):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(paths.shutil, "copyfile", _boom)

    # Still starts, reading the template in place.
    assert paths.ensure_config() == paths._TEMPLATE_CONFIG
