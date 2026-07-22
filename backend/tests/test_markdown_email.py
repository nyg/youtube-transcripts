"""markdown_email.render: the Markdown subset Claude emits -> email-safe HTML."""

from __future__ import annotations

import pytest

from yt_summarizer.markdown_email import render


# -- inline formatting -------------------------------------------------------


def test_bold_becomes_strong():
    assert "<strong>Bitcoin Market Position:</strong>" in render(
        "**Bitcoin Market Position:** Ivan has turned more bullish."
    )
    assert "**" not in render("**bold**")


def test_underscore_bold_and_italic():
    assert "<strong>loud</strong>" in render("__loud__")
    assert "<em>quiet</em>" in render("_quiet_")
    assert "<em>also quiet</em>" in render("*also quiet*")


def test_bold_inside_a_sentence_leaves_the_rest_alone():
    out = render("Ivan said **DCAing is fantastic** despite the downside.")
    assert out == (
        '<p style="margin:0 0 12px">Ivan said <strong>DCAing is fantastic</strong> '
        "despite the downside.</p>"
    )


def test_snake_case_is_not_italicised():
    assert "<em>" not in render("call video_id_lookup first")


def test_strikethrough_and_code_span():
    assert "<del>gone</del>" in render("~~gone~~")
    out = render("run `pip install **x**` now")
    assert "<code" in out and "**x**" in out and "<strong>" not in out


def test_links_are_rendered_and_unsafe_schemes_dropped():
    out = render("see [the docs](https://example.com/a?b=1&c=2)")
    assert 'href="https://example.com/a?b=1&amp;c=2"' in out
    assert ">the docs</a>" in out

    unsafe = render("[click](javascript:alert(1))")
    assert "javascript:" not in unsafe
    assert "<a " not in unsafe
    assert "click" in unsafe


# -- block structure ---------------------------------------------------------


def test_blank_line_splits_paragraphs_and_newline_becomes_break():
    assert render("one\ntwo") == '<p style="margin:0 0 12px">one<br>two</p>'
    assert render("one\n\ntwo").count("<p ") == 2


def test_headings():
    out = render("## Altcoins of Interest")
    assert out.startswith("<h2 ")
    assert ">Altcoins of Interest</h2>" in out
    assert render("##### deep").startswith("<h4 ")  # clamped to h4


def test_bullet_and_ordered_lists():
    bullets = render("- first\n- second")
    assert bullets.count("<li") == 2
    assert bullets.startswith("<ul ")

    ordered = render("1. first\n2. second")
    assert ordered.startswith("<ol ")
    assert ordered.count("<li") == 2


def test_switching_list_type_closes_the_previous_list():
    out = render("- bullet\n1. numbered")
    assert "</ul>" in out and "<ol " in out


def test_bullets_keep_inline_formatting():
    assert "<strong>Apple</strong>" in render("- **Apple** is at all-time highs")


def test_blockquote_and_horizontal_rule():
    assert render("> quoted").startswith("<blockquote ")
    assert "<hr " in render("---")


def test_fenced_code_block_is_literal():
    out = render("```\n**not bold**\n<b>raw</b>\n```")
    assert "<pre " in out
    assert "**not bold**" in out
    assert "&lt;b&gt;raw&lt;/b&gt;" in out
    assert "<strong>" not in out


def test_unterminated_fence_still_renders():
    assert "<pre " in render("```\ndangling")


# -- safety ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "tag"),
    [
        ("<script>alert(1)</script>", "<script"),
        ('<img src=x onerror="alert(1)">', "<img"),
        ('<a href="http://evil">hi</a>', '<a href="http://evil"'),
    ],
)
def test_raw_html_never_survives(payload, tag):
    """Summaries are model output — any HTML in them must arrive as visible text."""
    out = render(payload)
    assert tag not in out
    assert "&lt;" in out


def test_quotes_are_escaped():
    assert "&quot;" in render('he said "rebirth" in 2027')


def test_empty_input():
    assert render("") == ""
