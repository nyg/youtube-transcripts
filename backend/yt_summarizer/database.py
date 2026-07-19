"""SQLite persistence for processed video summaries."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS video_summaries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    published_at  TEXT,
    transcript    TEXT NOT NULL,
    prompt_name   TEXT NOT NULL,
    model         TEXT NOT NULL,
    ai_response   TEXT NOT NULL,
    tokens_input  INTEGER,
    tokens_output INTEGER,
    cost_usd      REAL,
    processed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    input      TEXT UNIQUE NOT NULL,
    label      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Databases created before multi-channel support lack the column.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(video_summaries)")}
            if "channel_id" not in columns:
                conn.execute("ALTER TABLE video_summaries ADD COLUMN channel_id INTEGER")

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_channels(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM channels ORDER BY id").fetchall()

    def get_channel(self, channel_id: int) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()

    def add_channel(self, input: str, label: str) -> sqlite3.Row:
        """Insert a channel and return its row. Raises sqlite3.IntegrityError on duplicates."""
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO channels (input, label, created_at) VALUES (?, ?, ?)",
                (input, label, created_at),
            )
            row = conn.execute(
                "SELECT * FROM channels WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        assert row is not None
        return row

    def delete_channel(self, channel_id: int) -> bool:
        """Delete a channel, keeping its summaries (channel_id set to NULL)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE video_summaries SET channel_id = NULL WHERE channel_id = ?",
                (channel_id,),
            )
            cursor = conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        return cursor.rowcount > 0

    def processed_ids(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT video_id FROM video_summaries").fetchall()
        return {row["video_id"] for row in rows}

    def published_dates(self) -> dict[str, str]:
        """video_id → stored (exact) publish date, for videos we have processed."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT video_id, published_at FROM video_summaries "
                "WHERE published_at IS NOT NULL"
            ).fetchall()
        return {row["video_id"]: row["published_at"] for row in rows}

    def save_summary(
        self,
        *,
        video_id: str,
        title: str,
        url: str,
        published_at: str | None,
        transcript: str,
        prompt_name: str,
        model: str,
        ai_response: str,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float | None,
        channel_id: int | None = None,
    ) -> None:
        processed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO video_summaries (
                    video_id, title, url, published_at, transcript, prompt_name,
                    model, ai_response, tokens_input, tokens_output, cost_usd,
                    processed_at, channel_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title=excluded.title,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    transcript=excluded.transcript,
                    prompt_name=excluded.prompt_name,
                    model=excluded.model,
                    ai_response=excluded.ai_response,
                    tokens_input=excluded.tokens_input,
                    tokens_output=excluded.tokens_output,
                    cost_usd=excluded.cost_usd,
                    processed_at=excluded.processed_at,
                    channel_id=excluded.channel_id
                """,
                (
                    video_id,
                    title,
                    url,
                    published_at,
                    transcript,
                    prompt_name,
                    model,
                    ai_response,
                    tokens_input,
                    tokens_output,
                    cost_usd,
                    processed_at,
                    channel_id,
                ),
            )

    def all_summaries(self, channel_id: int | None = None) -> list[sqlite3.Row]:
        """All summaries (optionally for one channel), latest published first."""
        query = "SELECT * FROM video_summaries"
        params: tuple = ()
        if channel_id is not None:
            query += " WHERE channel_id = ?"
            params = (channel_id,)
        query += " ORDER BY published_at DESC, processed_at DESC"
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def get_summary(self, video_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM video_summaries WHERE video_id = ?", (video_id,)
            ).fetchone()
