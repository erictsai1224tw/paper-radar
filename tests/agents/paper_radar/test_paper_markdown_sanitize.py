"""Tests for paper_markdown's sanitizer (the write-time one)."""
from __future__ import annotations

from paper_markdown import _sanitize_markdown


def test_sanitize_strips_control_bytes_keeps_printable_and_whitespace():
    s = "line1\x00x\n" + "tab\there\r\n" + "bell\x07done"
    out = _sanitize_markdown(s)
    assert out == "line1x\ntab\there\r\nbelldone"


def test_sanitize_is_noop_on_clean_text():
    clean = "Hello 世界\n# Header\n  - bullet\n"
    assert _sanitize_markdown(clean) == clean


def test_sanitize_handles_empty_string():
    assert _sanitize_markdown("") == ""
