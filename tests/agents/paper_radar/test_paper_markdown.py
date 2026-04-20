"""Tests for paper_markdown."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from paper_markdown import fetch_pdf_as_markdown


def _mock_resp(content: bytes = b"%PDF-fake") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_returns_existing_cache_without_download(tmp_path: Path):
    cached = tmp_path / "2501.00001.md"
    cached.write_text("already here", encoding="utf-8")
    with patch("paper_markdown.requests.get") as mock_get:
        out = fetch_pdf_as_markdown("2501.00001", tmp_path)
    assert out == cached
    assert mock_get.call_count == 0
    assert cached.read_text() == "already here"


def test_fetch_downloads_and_converts(tmp_path: Path):
    with patch("paper_markdown.requests.get", return_value=_mock_resp()) as mock_get, \
         patch("paper_markdown.MarkItDown") as mock_md_class:
        mock_md_class.return_value.convert.return_value.text_content = "# Title\n\nBody"
        out = fetch_pdf_as_markdown("2501.00002", tmp_path)

    assert mock_get.call_args.args[0] == "https://arxiv.org/pdf/2501.00002"
    assert out == tmp_path / "2501.00002.md"
    assert out.read_text(encoding="utf-8") == "# Title\n\nBody"


def test_fetch_returns_none_on_http_error(tmp_path: Path):
    resp = _mock_resp()
    resp.raise_for_status.side_effect = requests.HTTPError("404")
    with patch("paper_markdown.requests.get", return_value=resp):
        out = fetch_pdf_as_markdown("bad-id", tmp_path)
    assert out is None
    assert not (tmp_path / "bad-id.md").exists()


def test_fetch_returns_none_when_conversion_raises(tmp_path: Path):
    with patch("paper_markdown.requests.get", return_value=_mock_resp()), \
         patch("paper_markdown.MarkItDown") as mock_md_class:
        mock_md_class.return_value.convert.side_effect = RuntimeError("pdfminer boom")
        out = fetch_pdf_as_markdown("2501.00003", tmp_path)
    assert out is None
    assert not (tmp_path / "2501.00003.md").exists()


def test_fetch_creates_out_dir_if_missing(tmp_path: Path):
    target_dir = tmp_path / "nested" / "papers_md"
    with patch("paper_markdown.requests.get", return_value=_mock_resp()), \
         patch("paper_markdown.MarkItDown") as mock_md_class:
        mock_md_class.return_value.convert.return_value.text_content = "x"
        out = fetch_pdf_as_markdown("2501.00004", target_dir)
    assert out == target_dir / "2501.00004.md"
    assert out.exists()
