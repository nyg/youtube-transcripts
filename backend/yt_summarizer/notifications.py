"""Email delivery via the Resend REST API (used by the background monitor).

Reads no config itself — callers pass the API key, sender and recipients so this
stays a thin, testable transport. The key comes from RESEND_API_KEY in the .env
next to the config file, mirroring how ANTHROPIC_API_KEY is handled.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.resend.com/emails"


class NotificationError(Exception):
    """Raised when sending an email through Resend fails."""


def send_email(
    *,
    api_key: str,
    sender: str,
    recipients: Sequence[str],
    subject: str,
    html: str,
) -> None:
    """Send one HTML email to `recipients`. Raises NotificationError on failure."""
    if not api_key:
        raise NotificationError("RESEND_API_KEY is not set")
    if not recipients:
        raise NotificationError("No recipients configured for this channel")

    try:
        resp = httpx.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": sender,
                "to": list(recipients),
                "subject": subject,
                "html": html,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Resend returns a JSON body with a helpful message (e.g. unverified domain).
        detail = exc.response.text
        raise NotificationError(
            f"Resend API error {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise NotificationError(f"Could not reach the Resend API: {exc}") from exc

    log.info("Sent digest email to %d recipient(s)", len(recipients))
