"""Date handling: UTC ISO conversion and RSS feed date enrichment."""

from __future__ import annotations

from yt_summarizer import youtube_client
from yt_summarizer.youtube_client import _fetch_rss_dates, _to_epoch, _utc_iso

_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>aaa111</yt:videoId>
    <title>First</title>
    <published>2026-07-18T18:00:38+00:00</published>
  </entry>
  <entry>
    <yt:videoId>bbb222</yt:videoId>
    <title>Second</title>
    <published>2026-07-17T03:31:22+00:00</published>
  </entry>
</feed>
"""


def test_utc_iso_is_timezone_aware():
    # 2026-07-18T18:00:38Z
    assert _utc_iso(1784397638) == "2026-07-18T18:00:38+00:00"


def test_utc_iso_none_for_falsy():
    assert _utc_iso(None) is None
    assert _utc_iso(0) is None


def test_to_epoch_roundtrips_iso():
    assert _to_epoch("2026-07-18T18:00:38+00:00") == 1784397638


def test_to_epoch_returns_none_on_garbage():
    assert _to_epoch("not-a-date") is None


def test_fetch_rss_dates_parses_feed(monkeypatch):
    monkeypatch.setattr(youtube_client, "fetch_url", lambda url: _RSS)
    dates = _fetch_rss_dates("UC123")
    assert dates == {
        "aaa111": "2026-07-18T18:00:38+00:00",
        "bbb222": "2026-07-17T03:31:22+00:00",
    }


def test_fetch_rss_dates_empty_on_network_error(monkeypatch):
    def boom(url):
        raise youtube_client.YouTubeRateLimitError("429")

    monkeypatch.setattr(youtube_client, "fetch_url", boom)
    assert _fetch_rss_dates("UC123") == {}


def test_fetch_rss_dates_empty_on_malformed_xml(monkeypatch):
    monkeypatch.setattr(youtube_client, "fetch_url", lambda url: b"<not xml")
    assert _fetch_rss_dates("UC123") == {}
