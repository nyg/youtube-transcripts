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
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

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

    def processed_ids(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT video_id FROM video_summaries").fetchall()
        return {row["video_id"] for row in rows}

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
    ) -> None:
        processed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO video_summaries (
                    video_id, title, url, published_at, transcript, prompt_name,
                    model, ai_response, tokens_input, tokens_output, cost_usd, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    processed_at=excluded.processed_at
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
                ),
            )

    def all_summaries(self) -> list[sqlite3.Row]:
        """All summaries, latest published first."""
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM video_summaries
                ORDER BY published_at DESC, processed_at DESC
                """
            ).fetchall()
