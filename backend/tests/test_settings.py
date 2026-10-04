"""Where settings come from at startup, and how prompts move to model families."""

from __future__ import annotations

from app.main import _adopt_model_families
from app.settings import SettingsStore, load_settings
from yt_summarizer.config import parse_settings
from yt_summarizer.database import Database


def test_first_start_imports_the_config_file_and_stores_it(tmp_path):
    db = Database(tmp_path / "v.db")

    cfg = load_settings(db, {"max_videos_fetch": 10, "database": "v.db"})

    assert cfg.max_videos_fetch == 10
    assert db.get_settings()["max_videos_fetch"] == 10
    assert "database" not in db.get_settings()


def test_stored_settings_win_over_the_config_file(tmp_path):
    db = Database(tmp_path / "v.db")
    load_settings(db, {"max_videos_fetch": 10})

    cfg = load_settings(db, {"max_videos_fetch": 99})

    assert cfg.max_videos_fetch == 10


def test_replaced_settings_are_current_and_survive_a_restart(tmp_path):
    db = Database(tmp_path / "v.db")
    store = SettingsStore(db, load_settings(db, {}))

    store.replace(parse_settings({"max_videos_fetch": 40}))

    assert store.current.max_videos_fetch == 40
    assert load_settings(Database(tmp_path / "v.db"), {}).max_videos_fetch == 40


def test_prompts_storing_a_model_id_move_to_its_family(tmp_path):
    db = Database(tmp_path / "v.db")
    db.add_prompt("deep", "sys", 2000, model="claude-opus-5-5", effort="high")
    db.add_prompt("old", "sys", 2000, model="claude-sonnet-4-6", effort="low")
    db.add_prompt("family", "sys", 2000, model="haiku")
    db.add_prompt("foreign", "sys", 2000, model="gpt-5", effort="low")
    db.add_prompt("unset", "sys", 2000)

    _adopt_model_families(db)

    assert {row["name"]: row["model"] for row in db.list_prompts()} == {
        "deep": "opus",
        "old": "sonnet",
        "family": "haiku",
        "foreign": "gpt-5",
        "unset": None,
    }
    assert db.get_prompt_by_name("deep")["effort"] == "high"
