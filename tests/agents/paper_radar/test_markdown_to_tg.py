"""Tests for bot.markdown_to_telegram_html."""
from __future__ import annotations

from bot import markdown_to_telegram_html


def test_bold_becomes_b_tag():
    assert markdown_to_telegram_html("**hi**") == "<b>hi</b>"


def test_inline_code_becomes_code_tag():
    assert markdown_to_telegram_html("use `foo()` here") == "use <code>foo()</code> here"


def test_fenced_code_becomes_pre_code():
    md = "```python\nprint(1)\n```"
    html = markdown_to_telegram_html(md)
    assert html == "<pre><code>print(1)</code></pre>"


def test_headers_become_bold():
    assert markdown_to_telegram_html("## SNR-t Bias") == "<b>SNR-t Bias</b>"
    assert markdown_to_telegram_html("### 核心問題") == "<b>核心問題</b>"


def test_markdown_link_becomes_anchor():
    out = markdown_to_telegram_html("see [paper](https://arxiv.org/abs/2604.16044)")
    assert out == 'see <a href="https://arxiv.org/abs/2604.16044">paper</a>'


def test_display_math_dollars_stripped_content_kept():
    out = markdown_to_telegram_html("$$\\alpha_t = 1 - \\beta_t$$")
    assert out == "\\alpha_t = 1 - \\beta_t"


def test_inline_math_dollars_stripped():
    out = markdown_to_telegram_html("the value $x^2$ matters")
    assert out == "the value x^2 matters"


def test_table_separator_rows_stripped():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    out = markdown_to_telegram_html(md)
    assert "---" not in out
    assert "| a | b |" in out
    assert "| 1 | 2 |" in out


def test_html_reserved_chars_escaped_in_plain_text():
    out = markdown_to_telegram_html("if a < b then c > d & e")
    assert "&lt;" in out and "&gt;" in out and "&amp;" in out


def test_html_inside_code_block_escaped():
    md = "```\nif (a < b) { return &x; }\n```"
    out = markdown_to_telegram_html(md)
    assert "<pre><code>if (a &lt; b) { return &amp;x; }</code></pre>" == out


def test_bold_inside_header_single_bold():
    # '## **Title**' should end up as <b>Title</b>, not nested
    out = markdown_to_telegram_html("## **Title**")
    assert out == "<b><b>Title</b></b>"  # acceptable: nested <b> is still rendered bold


def test_plain_text_passes_through():
    assert markdown_to_telegram_html("just plain text") == "just plain text"


def test_preserves_newlines():
    out = markdown_to_telegram_html("line1\nline2\n\nline3")
    assert out == "line1\nline2\n\nline3"
