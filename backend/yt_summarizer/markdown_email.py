"""Render the Markdown subset Claude emits as inline-styled HTML for email.

The web UI renders summaries with react-markdown; the digest email has no such
luxury, so it needs real HTML. Mail clients also drop <style> blocks and reset
element defaults inconsistently, so every tag emitted here carries its own
inline style.

This is a deliberately small hand-rolled renderer rather than a Markdown
dependency: the input is model output going straight into someone's inbox, so
the text is HTML-escaped **first** and only the constructs below are turned back
into tags. Raw HTML in a summary can never reach the recipient.

Supported: headings, bullet/ordered lists, blockquotes, fenced code, horizontal
rules, paragraphs; inline bold, italic, strikethrough, code and links. Nested
lists are flattened — a digest doesn't need them.
"""

from __future__ import annotations

import html
import re

# -- styles (inline; mail clients ignore stylesheets) -----------------------

_PARAGRAPH = "margin:0 0 12px"
_HEADING_SIZES = {1: "18px", 2: "17px", 3: "16px", 4: "15px", 5: "14px", 6: "14px"}
_LIST = "margin:0 0 12px;padding-left:22px"
_LIST_ITEM = "margin:0 0 4px"
_QUOTE = "margin:0 0 12px;padding:0 0 0 12px;border-left:3px solid #ddd;color:#555"
_PRE = (
    "margin:0 0 12px;padding:10px;background:#f6f6f6;border-radius:4px;"
    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;"
    "overflow-x:auto;white-space:pre-wrap"
)
_CODE = (
    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;"
    "background:#f3f3f3;padding:1px 4px;border-radius:3px"
)
_RULE = "border:0;border-top:1px solid #e5e5e5;margin:16px 0"
_LINK = "color:#0b57d0"

# -- block patterns (matched against the stripped line) ---------------------

_HEADING = re.compile(r"(#{1,6})\s+(.*)")
_BULLET = re.compile(r"[-*+]\s+(.*)")
_ORDERED = re.compile(r"\d+[.)]\s+(.*)")
_QUOTED = re.compile(r">\s?(.*)")
_HRULE = re.compile(r"(?:-{3,}|\*{3,}|_{3,})\Z")

# -- inline patterns (applied to already-escaped text) ----------------------

_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK_SPAN = re.compile(r"\[([^\]\n]+)\]\(\s*([^)\s]+)[^)]*\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__", re.S)
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)
_ITALIC_STAR = re.compile(r"\*(?=\S)([^*]+?)(?<=\S)\*")
# Guarded so snake_case identifiers survive untouched.
_ITALIC_UNDERSCORE = re.compile(r"(?<![\w_])_(?=\S)([^_]+?)(?<=\S)_(?![\w_])")
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")

_SAFE_URL = re.compile(r"(?:https?://|mailto:)", re.I)


def render(text: str) -> str:
    """Render `text` as HTML. Never returns markup the input smuggled in."""
    lines = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    out: list[str] = []
    paragraph: list[str] = []
    quote: list[str] = []
    items: list[str] = []
    list_tag = ""
    code: list[str] | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f'<p style="{_PARAGRAPH}">{"<br>".join(paragraph)}</p>')
            paragraph = []

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            out.append(f'<blockquote style="{_QUOTE}">{"<br>".join(quote)}</blockquote>')
            quote = []

    def flush_list() -> None:
        nonlocal items, list_tag
        if items:
            body = "".join(f'<li style="{_LIST_ITEM}">{i}</li>' for i in items)
            out.append(f'<{list_tag} style="{_LIST}">{body}</{list_tag}>')
            items = []
            list_tag = ""

    def flush_all() -> None:
        flush_paragraph()
        flush_quote()
        flush_list()

    def flush_code(collected: list[str]) -> None:
        body = html.escape("\n".join(collected))
        out.append(f'<pre style="{_PRE}">{body}</pre>')

    for line in lines:
        stripped = line.strip()

        if code is not None:
            if stripped.startswith(("```", "~~~")):
                flush_code(code)
                code = None
            else:
                code.append(line)
            continue

        if stripped.startswith(("```", "~~~")):
            flush_all()
            code = []
            continue

        if not stripped:
            flush_all()
            continue

        if _HRULE.fullmatch(stripped):
            flush_all()
            out.append(f'<hr style="{_RULE}">')
            continue

        if match := _HEADING.fullmatch(stripped):
            flush_all()
            level = len(match.group(1))
            size = _HEADING_SIZES[level]
            tag = f"h{min(level, 4)}"  # nothing below h4 is worth its own tag here
            out.append(
                f'<{tag} style="margin:16px 0 6px;font-size:{size};font-weight:600">'
                f"{_inline(match.group(2))}</{tag}>"
            )
            continue

        if match := _QUOTED.fullmatch(stripped):
            flush_paragraph()
            flush_list()
            quote.append(_inline(match.group(1)))
            continue

        for tag, pattern in (("ul", _BULLET), ("ol", _ORDERED)):
            if match := pattern.fullmatch(stripped):
                flush_paragraph()
                flush_quote()
                if list_tag and list_tag != tag:
                    flush_list()
                list_tag = tag
                items.append(_inline(match.group(1)))
                break
        else:
            flush_quote()
            flush_list()
            paragraph.append(_inline(stripped))

    if code is not None:  # unterminated fence — emit what we collected
        flush_code(code)
    flush_all()

    return "".join(out)


def _inline(text: str) -> str:
    """Escape `text`, then turn inline Markdown back into tags."""
    escaped = html.escape(text)

    # Park code spans so emphasis markers inside them stay literal.
    spans: list[str] = []

    def stash(match: re.Match[str]) -> str:
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    escaped = _CODE_SPAN.sub(stash, escaped)

    escaped = _LINK_SPAN.sub(_link, escaped)
    escaped = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", escaped)
    escaped = _STRIKE.sub(lambda m: f"<del>{m.group(1)}</del>", escaped)
    escaped = _ITALIC_STAR.sub(lambda m: f"<em>{m.group(1)}</em>", escaped)
    escaped = _ITALIC_UNDERSCORE.sub(lambda m: f"<em>{m.group(1)}</em>", escaped)

    return _PLACEHOLDER.sub(
        lambda m: f'<code style="{_CODE}">{spans[int(m.group(1))]}</code>', escaped
    )


def _link(match: re.Match[str]) -> str:
    label, url = match.group(1), match.group(2)
    # url is already HTML-escaped, so it is safe in an attribute; only the
    # scheme still needs vetting (no javascript:/data: in someone's inbox).
    if not _SAFE_URL.match(url):
        return label
    return f'<a href="{url}" style="{_LINK}">{label}</a>'
