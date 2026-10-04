"""Settings parsing, and what an older config.yaml still contributes."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt_summarizer.config import (
    DEFAULT_PRICING,
    ConfigError,
    ModelPricing,
    legacy_settings,
    parse_settings,
    read_config_file,
    settings_to_raw,
)


def test_schedule_defaults_to_hourly():
    cfg = parse_settings({"monitoring": {"enabled": False}})
    assert cfg.monitor.schedule == "0 * * * *"
    assert cfg.monitor.run_on_start is True


def test_schedule_is_read():
    cfg = parse_settings({"monitoring": {"schedule": "*/15 * * * *", "run_on_start": False}})
    assert cfg.monitor.schedule == "*/15 * * * *"
    assert cfg.monitor.run_on_start is False


def test_invalid_cron_expression_is_rejected():
    with pytest.raises(ConfigError, match="not a valid cron expression"):
        parse_settings({"monitoring": {"schedule": "every hour"}})


def test_legacy_interval_minutes_is_rejected():
    """Silently ignoring it would change the cadence without a word."""
    with pytest.raises(ConfigError, match="schedule"):
        parse_settings({"monitoring": {"interval_minutes": 60}})


def test_interval_minutes_tolerated_alongside_schedule():
    cfg = parse_settings({"monitoring": {"interval_minutes": 60, "schedule": "0 8 * * *"}})
    assert cfg.monitor.schedule == "0 8 * * *"


def test_resend_from_required_when_enabled():
    with pytest.raises(ConfigError, match="resend_from"):
        parse_settings({"monitoring": {"enabled": True}})


def test_ask_output_cap_defaults_and_is_read():
    assert parse_settings({"ask": {}}).ask.max_output_tokens == 8192
    assert parse_settings({"ask": {"max_output_tokens": 16000}}).ask.max_output_tokens == 16000


def test_ask_output_cap_must_be_positive():
    with pytest.raises(ConfigError, match="ask.max_output_tokens"):
        parse_settings({"ask": {"max_output_tokens": 0}})


@pytest.mark.parametrize(
    "raw,message",
    [
        ({"max_videos_fetch": 0}, "max_videos_fetch"),
        ({"max_videos_fetch": "many"}, "Invalid setting"),
        ({"youtube_request_interval": -1}, "youtube_request_interval"),
        ({"pricing": {"opus": {"input": 4}}}, "pricing entry for 'opus'"),
        ({"pricing": {"opus": {"input": -1, "output": 20}}}, "cannot be negative"),
        ({"monitoring": {"daily_budget_usd": -1}}, "daily_budget_usd"),
        ({"monitoring": {"max_age_hours": -1}}, "max_age_hours"),
    ],
)
def test_out_of_range_settings_are_rejected(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_settings(raw)


def test_every_family_is_priced_even_when_none_is_given():
    cfg = parse_settings({"pricing": {"opus": {"input": 6, "output": 30}, "gpt": {"input": 1}}})

    assert cfg.pricing == {**DEFAULT_PRICING, "opus": ModelPricing(6.0, 30.0)}
    assert cfg.priced_models == {
        "fable": "claude-fable-5-1",
        "opus": "claude-opus-5-5",
        "sonnet": "claude-sonnet-5-5",
        "haiku": "claude-haiku-4-5",
    }


def test_settings_survive_a_round_trip_through_their_stored_form():
    cfg = parse_settings(
        {
            "max_videos_fetch": 40,
            "transcript_languages": ["fr", " en ", ""],
            "cookies_file": "/tmp/cookies.txt",
            "pricing": {"haiku": {"input": 0.5, "output": 2.5}},
            "priced_models": {"opus": "claude-opus-6"},
            "monitoring": {"enabled": True, "resend_from": "me@example.com"},
            "ask": {"max_context_tokens": 50_000},
        }
    )

    assert parse_settings(settings_to_raw(cfg)) == cfg
    assert cfg.transcript_languages == ("fr", "en")
    assert cfg.cookies_file == Path("/tmp/cookies.txt")
    assert cfg.priced_models["opus"] == "claude-opus-6"


def test_config_file_must_exist_and_hold_a_mapping(tmp_path):
    listing = tmp_path / "config.yaml"
    listing.write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="not found"):
        read_config_file(tmp_path / "missing.yaml")
    with pytest.raises(ConfigError, match="YAML mapping"):
        read_config_file(listing)


def test_an_older_config_file_carries_its_settings_over(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "max_videos_fetch: 10\n"
        "database: elsewhere.db\n"
        "prompts: {old: text}\n"
        "pricing:\n"
        "  claude-opus-5-5: {input: 6.0, output: 30.0}\n"
        "  claude-sonnet-5: {input: 3.0, output: 15.0}\n"
        "  some-other-model: {input: 1.0, output: 1.0}\n"
        "monitoring:\n"
        '  schedule: "0 8 * * *"\n',
        encoding="utf-8",
    )

    legacy = legacy_settings(read_config_file(path))
    cfg = parse_settings(legacy)

    assert set(legacy) == {"max_videos_fetch", "pricing", "monitoring"}
    assert cfg.max_videos_fetch == 10
    assert cfg.monitor.schedule == "0 8 * * *"
    assert cfg.pricing["opus"] == ModelPricing(6.0, 30.0)
    assert cfg.pricing["sonnet"] == DEFAULT_PRICING["sonnet"]


def test_the_bundled_template_holds_no_settings():
    template = Path(__file__).resolve().parents[1] / "config.example.yaml"

    assert legacy_settings(read_config_file(template)) == {}
