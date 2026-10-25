"""Resend transport guard clauses (no network involved)."""

from __future__ import annotations

import pytest

from yt_summarizer.notifications import NotificationError, send_email


def test_send_email_requires_api_key():
    with pytest.raises(NotificationError):
        send_email(api_key="", sender="a@b.com", recipients=["x@y.com"],
                   subject="s", html="<p>h</p>")


def test_send_email_requires_recipients():
    with pytest.raises(NotificationError):
        send_email(api_key="re_test", sender="a@b.com", recipients=[],
                   subject="s", html="<p>h</p>")
