from __future__ import annotations

from dataclasses import dataclass

from .database import Database

CHARS_PER_TOKEN = 4
SUMMARY_BUDGET_SHARE = 0.6
MAX_MENTION_LINES = 400
MAX_EXCERPTS = 40

_STOPWORDS = {
    "a", "about", "after", "all", "also", "am", "an", "and", "any", "are", "as", "at",
    "be", "been", "before", "being", "between", "but", "by", "can", "did", "do", "does",
    "doing", "done", "for", "from", "had", "has", "have", "he", "her", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "just", "last", "like", "me",
    "month", "more", "most", "my", "no", "not", "now", "of", "on", "one", "only", "or",
    "our", "out", "over", "said", "say", "says", "she", "should", "since", "so", "some",
    "still", "such", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "think", "this", "those", "to", "up", "us", "was", "we", "week", "were",
    "what", "when", "where", "which", "while", "who", "why", "will", "with", "would",
    "year", "you", "your",
}


@dataclass(frozen=True)
class Source:
    number: int
    kind: str
    video_id: str
    title: str
    url: str
    published_at: str | None
    start_seconds: int | None = None


@dataclass(frozen=True)
class Context:
    text: str
    sources: list[Source]
    mention_count: int
    summary_count: int
    excerpt_count: int


def _stamp(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _date(value: str | None) -> str:
    return (value or "")[:10] or "undated"


def search_terms(question: str) -> str:
    words = [
        word
        for word in "".join(c if c.isalnum() or c.isspace() else " " for c in question).split()
        if len(word) > 2 and word.lower() not in _STOPWORDS
    ]
    return " ".join(words)


def build_context(
    db: Database,
    question: str,
    *,
    channel_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
    max_tokens: int = 100_000,
) -> Context:
    budget = max_tokens * CHARS_PER_TOKEN
    blocks: list[str] = []
    sources: list[Source] = []
    used = 0

    def add(block: str, source: Source) -> bool:
        nonlocal used
        if used + len(block) > budget:
            return False
        blocks.append(block)
        sources.append(source)
        used += len(block)
        return True

    mention_count = 0
    for row in db.list_mentions(
        channel_id=channel_id, since=since, until=until, limit=MAX_MENTION_LINES
    ):
        number = len(sources) + 1
        at = f" @ {_stamp(row['timestamp_seconds'])}" if row["timestamp_seconds"] else ""
        line = (
            f"[{number}] mention · {_date(row['published_at'])} · {row['title']}{at}\n"
            f"{row['entity']}: {row['stance']} ({row['confidence']} confidence) — "
            f"{row['rationale'] or ''} \"{row['quote'] or ''}\"\n"
        )
        if not add(
            line,
            Source(
                number=number,
                kind="mention",
                video_id=row["video_id"],
                title=row["title"],
                url=row["url"],
                published_at=row["published_at"],
                start_seconds=row["timestamp_seconds"],
            ),
        ):
            break
        mention_count += 1

    summary_budget = used + (budget - used) * SUMMARY_BUDGET_SHARE
    summary_count = 0
    for row in db.all_summaries(channel_id):
        published = row["published_at"] or row["processed_at"]
        if since and published < since:
            continue
        if until and published > until:
            continue
        number = len(sources) + 1
        block = (
            f"[{number}] summary · {_date(row['published_at'])} · {row['title']}\n"
            f"{row['ai_response']}\n"
        )
        if used + len(block) > summary_budget:
            break
        if not add(
            block,
            Source(
                number=number,
                kind="summary",
                video_id=row["video_id"],
                title=row["title"],
                url=row["url"],
                published_at=row["published_at"],
            ),
        ):
            break
        summary_count += 1

    excerpt_count = 0
    terms = search_terms(question)
    if terms:
        for row in db.search(
            terms, channel_id=channel_id, since=since, limit=MAX_EXCERPTS, mode="or"
        ):
            if row["kind"] != "transcript":
                continue
            number = len(sources) + 1
            at = f" @ {_stamp(row['start_seconds'])}" if row["start_seconds"] is not None else ""
            block = (
                f"[{number}] excerpt · {_date(row['published_at'])} · {row['title']}{at}\n"
                f"{row['text']}\n"
            )
            if not add(
                block,
                Source(
                    number=number,
                    kind="excerpt",
                    video_id=row["video_id"],
                    title=row["title"],
                    url=row["url"],
                    published_at=row["published_at"],
                    start_seconds=row["start_seconds"],
                ),
            ):
                break
            excerpt_count += 1

    return Context(
        text="\n".join(blocks),
        sources=sources,
        mention_count=mention_count,
        summary_count=summary_count,
        excerpt_count=excerpt_count,
    )
