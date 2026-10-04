"""SQLite persistence for processed video summaries."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .chunking import Chunk, build_chunks, fts_query
from .config import DEFAULT_MAX_OUTPUT_TOKENS
from .mentions import Mention, entity_key
from .transcripts import segments_from_json

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
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    input         TEXT UNIQUE NOT NULL,
    label         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    prompt_name   TEXT,
    notify_emails TEXT
);

CREATE TABLE IF NOT EXISTS prompts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT UNIQUE NOT NULL,
    text                    TEXT NOT NULL,
    estimated_output_tokens INTEGER NOT NULL DEFAULT 2000,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mentions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id          TEXT NOT NULL,
    channel_id        INTEGER,
    prompt_name       TEXT NOT NULL,
    entity            TEXT NOT NULL,
    entity_key        TEXT NOT NULL,
    stance            TEXT NOT NULL,
    confidence        TEXT NOT NULL,
    rationale         TEXT,
    quote             TEXT,
    timestamp_seconds INTEGER,
    published_at      TEXT,
    processed_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS mentions_entity ON mentions (entity_key, published_at);
CREATE INDEX IF NOT EXISTS mentions_video ON mentions (video_id);

CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id    INTEGER,
    question      TEXT NOT NULL,
    since         TEXT,
    until         TEXT,
    answer        TEXT NOT NULL,
    sources       TEXT NOT NULL,
    model         TEXT NOT NULL,
    tokens_input  INTEGER,
    tokens_output INTEGER,
    cost_usd      REAL,
    created_at    TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    text,
    video_id UNINDEXED,
    kind UNINDEXED,
    start_seconds UNINDEXED,
    tokenize='porter unicode61 remove_diacritics 2'
);
"""


# How a summary was produced; NULL on rows saved before these were recorded.
_RUN_STATS_COLUMNS = {
    "effort": "TEXT",
    "max_output_tokens": "INTEGER",
    "estimated_output_tokens": "INTEGER",
    "tokens_thinking": "INTEGER",
    "stop_reason": "TEXT",
    "duration_ms": "INTEGER",
}


def _replace_chunks(conn: sqlite3.Connection, video_id: str, chunks: Sequence[Chunk]) -> None:
    conn.execute("DELETE FROM chunks WHERE video_id = ?", (video_id,))
    conn.executemany(
        "INSERT INTO chunks (text, video_id, kind, start_seconds) VALUES (?, ?, ?, ?)",
        [(chunk.text, video_id, chunk.kind, chunk.start_seconds) for chunk in chunks],
    )


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
            if "transcript_segments" not in columns:
                conn.execute("ALTER TABLE video_summaries ADD COLUMN transcript_segments TEXT")
            for column, kind in _RUN_STATS_COLUMNS.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE video_summaries ADD COLUMN {column} {kind}")
            prompt_columns = {row[1] for row in conn.execute("PRAGMA table_info(prompts)")}
            if "entity_kind" not in prompt_columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN entity_kind TEXT")
            if "stance_labels" not in prompt_columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN stance_labels TEXT")
            # Older prompts ran on a global model; theirs stay unset until chosen.
            if "model" not in prompt_columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN model TEXT")
            if "effort" not in prompt_columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN effort TEXT")
            if "max_output_tokens" not in prompt_columns:
                conn.execute(
                    "ALTER TABLE prompts ADD COLUMN max_output_tokens "
                    f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_OUTPUT_TOKENS}"
                )
            # Databases created before per-channel prompts / recipients lack these.
            channel_columns = {row[1] for row in conn.execute("PRAGMA table_info(channels)")}
            if "prompt_name" not in channel_columns:
                conn.execute("ALTER TABLE channels ADD COLUMN prompt_name TEXT")
            if "notify_emails" not in channel_columns:
                conn.execute("ALTER TABLE channels ADD COLUMN notify_emails TEXT")

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

    def add_channel(
        self,
        input: str,
        label: str,
        prompt_name: str | None = None,
        notify_emails: list[str] | None = None,
    ) -> sqlite3.Row:
        """Insert a channel and return its row. Raises sqlite3.IntegrityError on duplicates."""
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO channels (input, label, created_at, prompt_name, notify_emails) "
                "VALUES (?, ?, ?, ?, ?)",
                (input, label, created_at, prompt_name, json.dumps(notify_emails or [])),
            )
            row = conn.execute(
                "SELECT * FROM channels WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        assert row is not None
        return row

    def update_channel(
        self,
        channel_id: int,
        *,
        prompt_name: str | None = None,
        notify_emails: list[str] | None = None,
    ) -> sqlite3.Row | None:
        """Update a channel's prompt and/or recipient list.

        Only arguments that are not None are applied (pass an empty list to clear
        recipients). Returns the updated row, or None if the channel is missing.
        """
        sets: list[str] = []
        params: list[object] = []
        if prompt_name is not None:
            sets.append("prompt_name = ?")
            params.append(prompt_name)
        if notify_emails is not None:
            sets.append("notify_emails = ?")
            params.append(json.dumps(notify_emails))
        if not sets:
            return self.get_channel(channel_id)
        params.append(channel_id)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE channels SET {', '.join(sets)} WHERE id = ?", params
            )
            if cursor.rowcount == 0:
                return None
            return conn.execute(
                "SELECT * FROM channels WHERE id = ?", (channel_id,)
            ).fetchone()

    def delete_channel(self, channel_id: int) -> bool:
        """Delete a channel, keeping its summaries (channel_id set to NULL)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE video_summaries SET channel_id = NULL WHERE channel_id = ?",
                (channel_id,),
            )
            cursor = conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        return cursor.rowcount > 0

    # -- prompts -----------------------------------------------------------

    def list_prompts(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM prompts ORDER BY id").fetchall()

    def get_prompt(self, prompt_id: int) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()

    def get_prompt_by_name(self, name: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM prompts WHERE name = ?", (name,)).fetchone()

    def add_prompt(
        self,
        name: str,
        text: str,
        estimated_output_tokens: int,
        entity_kind: str | None = None,
        stance_labels: list[str] | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> sqlite3.Row:
        """Insert a prompt and return its row. Raises sqlite3.IntegrityError on a duplicate name."""
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO prompts (name, text, estimated_output_tokens, created_at, "
                "entity_kind, stance_labels, model, effort, max_output_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    text,
                    estimated_output_tokens,
                    created_at,
                    entity_kind or None,
                    json.dumps(stance_labels) if stance_labels else None,
                    model,
                    effort,
                    max_output_tokens,
                ),
            )
            row = conn.execute(
                "SELECT * FROM prompts WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        assert row is not None
        return row

    def update_prompt(
        self,
        prompt_id: int,
        *,
        text: str | None = None,
        estimated_output_tokens: int | None = None,
        entity_kind: str | None = None,
        stance_labels: list[str] | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> sqlite3.Row | None:
        """Update the given fields of a prompt (its name is immutable, since channels
        reference it by name). Returns the updated row, or None if missing.
"""
        sets: list[str] = []
        params: list[object] = []
        if text is not None:
            sets.append("text = ?")
            params.append(text)
        if estimated_output_tokens is not None:
            sets.append("estimated_output_tokens = ?")
            params.append(estimated_output_tokens)
        if entity_kind is not None:
            sets.append("entity_kind = ?")
            params.append(entity_kind or None)
        if stance_labels is not None:
            sets.append("stance_labels = ?")
            params.append(json.dumps(stance_labels) if stance_labels else None)
        for column, value in (
            ("model", model),
            ("effort", effort),
            ("max_output_tokens", max_output_tokens),
        ):
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        if not sets:
            return self.get_prompt(prompt_id)
        params.append(prompt_id)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE prompts SET {', '.join(sets)} WHERE id = ?", params
            )
            if cursor.rowcount == 0:
                return None
            return conn.execute(
                "SELECT * FROM prompts WHERE id = ?", (prompt_id,)
            ).fetchone()

    def delete_prompt(self, prompt_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        return cursor.rowcount > 0

    def channels_using_prompt(self, name: str) -> list[sqlite3.Row]:
        """Channels that reference the prompt `name` (used to guard prompt deletion)."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM channels WHERE prompt_name = ? ORDER BY id", (name,)
            ).fetchall()

    def processed_ids(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT video_id FROM video_summaries").fetchall()
        return {row["video_id"] for row in rows}

    def spend_since(self, iso_start: str) -> float:
        """Total cost_usd of summaries processed at or after `iso_start` (UTC ISO).

        Reprocessing upserts processed_at, so a video (re)processed today counts
        toward today. Rows with a NULL cost (models without pricing) are ignored.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(("
                "  SELECT SUM(cost_usd) FROM video_summaries WHERE processed_at >= ?"
                "), 0) + COALESCE(("
                "  SELECT SUM(cost_usd) FROM questions WHERE created_at >= ?"
                "), 0) AS total",
                (iso_start, iso_start),
            ).fetchone()
        return float(row["total"] or 0.0)

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
        transcript_segments: str | None = None,
        mentions: Sequence[Mention] = (),
        effort: str | None = None,
        max_output_tokens: int | None = None,
        estimated_output_tokens: int | None = None,
        tokens_thinking: int | None = None,
        stop_reason: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        processed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO video_summaries (
                    video_id, title, url, published_at, transcript, prompt_name,
                    model, ai_response, tokens_input, tokens_output, cost_usd,
                    processed_at, channel_id, transcript_segments,
                    effort, max_output_tokens, estimated_output_tokens,
                    tokens_thinking, stop_reason, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    channel_id=excluded.channel_id,
                    transcript_segments=excluded.transcript_segments,
                    effort=excluded.effort,
                    max_output_tokens=excluded.max_output_tokens,
                    estimated_output_tokens=excluded.estimated_output_tokens,
                    tokens_thinking=excluded.tokens_thinking,
                    stop_reason=excluded.stop_reason,
                    duration_ms=excluded.duration_ms
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
                    transcript_segments,
                    effort,
                    max_output_tokens,
                    estimated_output_tokens,
                    tokens_thinking,
                    stop_reason,
                    duration_ms,
                ),
            )
            conn.execute("DELETE FROM mentions WHERE video_id = ?", (video_id,))
            _replace_chunks(
                conn,
                video_id,
                build_chunks(transcript, segments_from_json(transcript_segments), ai_response),
            )
            conn.executemany(
                """
                INSERT INTO mentions (
                    video_id, channel_id, prompt_name, entity, entity_key, stance,
                    confidence, rationale, quote, timestamp_seconds, published_at,
                    processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        video_id,
                        channel_id,
                        prompt_name,
                        mention.entity,
                        entity_key(mention.entity),
                        mention.stance,
                        mention.confidence,
                        mention.rationale,
                        mention.quote,
                        mention.timestamp_seconds,
                        published_at,
                        processed_at,
                    )
                    for mention in mentions
                ],
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

    def delete_summary(self, video_id: str) -> bool:
        """Delete a summary. The video becomes unprocessed and can be redone."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM video_summaries WHERE video_id = ?", (video_id,)
            )
            conn.execute("DELETE FROM mentions WHERE video_id = ?", (video_id,))
            conn.execute("DELETE FROM chunks WHERE video_id = ?", (video_id,))
        return cursor.rowcount > 0

    # -- mentions ----------------------------------------------------------

    def list_mentions(
        self,
        *,
        channel_id: int | None = None,
        entity: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        query = (
            "SELECT m.*, v.title AS title, v.url AS url "
            "FROM mentions m JOIN video_summaries v ON v.video_id = m.video_id"
        )
        clauses: list[str] = []
        params: list[object] = []
        if channel_id is not None:
            clauses.append("m.channel_id = ?")
            params.append(channel_id)
        if entity:
            clauses.append("m.entity_key = ?")
            params.append(entity_key(entity))
        if since:
            clauses.append("COALESCE(m.published_at, m.processed_at) >= ?")
            params.append(since)
        if until:
            clauses.append("COALESCE(m.published_at, m.processed_at) <= ?")
            params.append(until)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY COALESCE(m.published_at, m.processed_at) DESC, m.id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def entity_overview(
        self, *, channel_id: int | None = None, since: str | None = None
    ) -> list[dict]:
        rows = self.list_mentions(channel_id=channel_id, since=since, limit=100_000)
        overview: dict[str, dict] = {}
        for row in rows:  # newest first
            key = row["entity_key"]
            at = row["published_at"] or row["processed_at"]
            entry = overview.get(key)
            if entry is None:
                overview[key] = {
                    "entity_key": key,
                    "entity": row["entity"],
                    "latest_stance": row["stance"],
                    "latest_at": at,
                    "latest_video_id": row["video_id"],
                    "previous_stance": None,
                    "previous_at": None,
                    "mention_count": 1,
                    "video_ids": {row["video_id"]},
                }
                continue
            entry["mention_count"] += 1
            entry["video_ids"].add(row["video_id"])
            if entry["previous_stance"] is None and row["stance"] != entry["latest_stance"]:
                entry["previous_stance"] = row["stance"]
                entry["previous_at"] = at
        result = []
        for entry in overview.values():
            video_ids = entry.pop("video_ids")
            entry["video_count"] = len(video_ids)
            result.append(entry)
        result.sort(key=lambda e: (e["latest_at"] or "", e["mention_count"]), reverse=True)
        return result

    def mentions_for_videos(self, video_ids: Sequence[str]) -> dict[str, list[sqlite3.Row]]:
        if not video_ids:
            return {}
        placeholders = ",".join("?" * len(video_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM mentions WHERE video_id IN ({placeholders}) ORDER BY id",
                tuple(video_ids),
            ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["video_id"], []).append(row)
        return grouped

    def known_entities(self, prompt_name: str, limit: int = 200) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT entity, COUNT(*) AS uses FROM mentions WHERE prompt_name = ? "
                "GROUP BY entity_key ORDER BY uses DESC, entity LIMIT ?",
                (prompt_name, limit),
            ).fetchall()
        return [row["entity"] for row in rows]

    def get_summary(self, video_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM video_summaries WHERE video_id = ?", (video_id,)
            ).fetchone()

    # -- search ------------------------------------------------------------

    def backfill_chunks(self) -> int:
        with self._connect() as conn:
            indexed = {row[0] for row in conn.execute("SELECT DISTINCT video_id FROM chunks")}
            rows = conn.execute(
                "SELECT video_id, transcript, transcript_segments, ai_response "
                "FROM video_summaries"
            ).fetchall()
            missing = [row for row in rows if row["video_id"] not in indexed]
            for row in missing:
                _replace_chunks(
                    conn,
                    row["video_id"],
                    build_chunks(
                        row["transcript"],
                        segments_from_json(row["transcript_segments"]),
                        row["ai_response"],
                    ),
                )
        return len(missing)

    def search(
        self,
        text: str,
        *,
        channel_id: int | None = None,
        since: str | None = None,
        limit: int = 50,
        mode: str = "and",
    ) -> list[sqlite3.Row]:
        match = fts_query(text, mode)
        if match is None:
            return []
        query = (
            "SELECT chunks.video_id AS video_id, chunks.kind AS kind, "
            "chunks.start_seconds AS start_seconds, chunks.text AS text, "
            "snippet(chunks, 0, char(2), char(3), '…', 24) AS snippet, "
            "bm25(chunks) AS rank, v.title AS title, v.url AS url, "
            "v.published_at AS published_at, v.channel_id AS channel_id "
            "FROM chunks JOIN video_summaries v ON v.video_id = chunks.video_id "
            "WHERE chunks MATCH ?"
        )
        params: list[object] = [match]
        if channel_id is not None:
            query += " AND v.channel_id = ?"
            params.append(channel_id)
        if since:
            query += " AND COALESCE(v.published_at, v.processed_at) >= ?"
            params.append(since)
        query += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    # -- questions ---------------------------------------------------------

    def save_question(
        self,
        *,
        channel_id: int | None,
        question: str,
        since: str | None,
        until: str | None,
        answer: str,
        sources: list[dict],
        model: str,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float | None,
    ) -> sqlite3.Row:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO questions (channel_id, question, since, until, answer, sources, "
                "model, tokens_input, tokens_output, cost_usd, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    channel_id,
                    question,
                    since,
                    until,
                    answer,
                    json.dumps(sources),
                    model,
                    tokens_input,
                    tokens_output,
                    cost_usd,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM questions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        assert row is not None
        return row

    def list_questions(self, channel_id: int | None = None, limit: int = 50) -> list[sqlite3.Row]:
        query = "SELECT * FROM questions"
        params: list[object] = []
        if channel_id is not None:
            query += " WHERE channel_id = ?"
            params.append(channel_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def delete_question(self, question_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        return cursor.rowcount > 0
