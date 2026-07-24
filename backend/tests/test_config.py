"""Config parsing: the monitoring schedule in particular."""

from __future__ import annotations

import pytest

from yt_summarizer.config import ConfigError, load_config


def _write(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_schedule_defaults_to_hourly(tmp_path):
    cfg = load_config(_write(tmp_path, "monitoring:\n  enabled: false\n"))
    assert cfg.monitor.schedule == "0 * * * *"
    assert cfg.monitor.run_on_start is True


def test_schedule_is_read(tmp_path):
    cfg = load_config(_write(tmp_path, 'monitoring:\n  schedule: "*/15 * * * *"\n  run_on_start: false\n'))
    assert cfg.monitor.schedule == "*/15 * * * *"
    assert cfg.monitor.run_on_start is False


def test_invalid_cron_expression_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="not a valid cron expression"):
        load_config(_write(tmp_path, 'monitoring:\n  schedule: "every hour"\n'))


def test_legacy_interval_minutes_is_rejected(tmp_path):
    """Silently ignoring it would change the cadence without a word."""
    with pytest.raises(ConfigError, match="schedule"):
        load_config(_write(tmp_path, "monitoring:\n  interval_minutes: 60\n"))


def test_interval_minutes_tolerated_alongside_schedule(tmp_path):
    cfg = load_config(
        _write(tmp_path, 'monitoring:\n  interval_minutes: 60\n  schedule: "0 8 * * *"\n')
    )
    assert cfg.monitor.schedule == "0 8 * * *"


def test_resend_from_required_when_enabled(tmp_path):
    with pytest.raises(ConfigError, match="resend_from"):
        load_config(_write(tmp_path, "monitoring:\n  enabled: true\n"))
