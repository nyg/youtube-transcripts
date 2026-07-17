"""Render processed summaries into a single self-contained HTML report."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_report(rows: Sequence[sqlite3.Row], output_path: Path, channel: str) -> Path:
    md = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("report.html.j2")

    items = []
    total_cost = 0.0
    for row in rows:
        cost = row["cost_usd"]
        if cost is not None:
            total_cost += cost
        items.append(
            {
                "title": row["title"],
                "url": row["url"],
                "published": (row["published_at"] or "unknown date")[:10],
                "prompt_name": row["prompt_name"],
                "model": row["model"],
                "tokens_input": row["tokens_input"] or 0,
                "tokens_output": row["tokens_output"] or 0,
                "cost": f"${cost:.4f}" if cost is not None else "n/a",
                "processed": (row["processed_at"] or "")[:10],
                # Claude responses are Markdown — render to HTML here, mark
                # safe in the template.
                "response_html": md.render(row["ai_response"] or ""),
            }
        )

    html = template.render(
        channel=channel,
        items=items,
        total_cost=f"${total_cost:.4f}",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    log.debug("Wrote HTML report with %d entries to %s", len(items), output_path)
    return output_path
