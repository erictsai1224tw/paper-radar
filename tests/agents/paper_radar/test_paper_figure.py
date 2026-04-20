"""Tests for paper_figure."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from paper_figure import fetch_first_figure


def _mock_resp(content: bytes = b"%PDF-fake") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def _mock_doc_with_fig1_on_page(page_idx: int, caption_text: str = "Figure 1: our method does X.") -> MagicMock:
    """Return a mock pymupdf Document whose page `page_idx` has Figure 1 caption."""
    doc = MagicMock()
    doc.page_count = page_idx + 3
    pages = []
    for i in range(doc.page_count):
        page = MagicMock()
        if i == page_idx:
            page.get_text.return_value = f"some body\n{caption_text}\nmore text"
        else:
            page.get_text.return_value = "body text, no figure caption"
        pix = MagicMock()
        pix.save = MagicMock()
        page.get_pixmap.return_value = pix
        pages.append(page)
    doc.__getitem__.side_effect = lambda idx: pages[idx]
    doc.close = MagicMock()
    return doc


def test_fetch_returns_existing_cache(tmp_path: Path):
    (tmp_path / "2501.00001.png").write_bytes(b"\x89PNG cached")
    (tmp_path / "2501.00001.caption.txt").write_text("cached caption", encoding="utf-8")
    with patch("paper_figure.requests.get") as mock_get:
        out = fetch_first_figure("2501.00001", tmp_path)
    assert mock_get.call_count == 0
    assert out == (tmp_path / "2501.00001.png", "cached caption")


def test_fetch_renders_page_with_figure_1(tmp_path: Path):
    doc = _mock_doc_with_fig1_on_page(1, "Figure 1: overview of XYZ method.")
    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00002", tmp_path)

    assert out is not None
    png_path, caption = out
    assert png_path == tmp_path / "2501.00002.png"
    assert caption == "overview of XYZ method."
    # caption.txt written
    assert (tmp_path / "2501.00002.caption.txt").read_text() == "overview of XYZ method."
    # render called only on the matching page
    assert doc[1].get_pixmap.called
    assert not doc[0].get_pixmap.called


def test_fetch_returns_none_on_http_error(tmp_path: Path):
    resp = _mock_resp()
    resp.raise_for_status.side_effect = requests.HTTPError("404")
    with patch("paper_figure.requests.get", return_value=resp):
        out = fetch_first_figure("bad-id", tmp_path)
    assert out is None
    assert not (tmp_path / "bad-id.png").exists()


def test_fetch_returns_none_when_no_figure_1_found(tmp_path: Path):
    doc = MagicMock()
    doc.page_count = 3
    pages = [MagicMock(), MagicMock(), MagicMock()]
    for p in pages:
        p.get_text.return_value = "no figure mentioned here"
    doc.__getitem__.side_effect = lambda i: pages[i]
    doc.close = MagicMock()
    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00003", tmp_path)
    assert out is None


def test_fetch_accepts_fig_dot_variant(tmp_path: Path):
    doc = _mock_doc_with_fig1_on_page(0, "Fig. 1: short caption.")
    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00004", tmp_path)
    assert out is not None
    assert out[1] == "short caption."


def test_fetch_returns_empty_caption_when_marker_present_but_content_too_short(tmp_path: Path):
    # 'Figure 1:' with only 5 chars after won't match the {10,500} range
    doc = _mock_doc_with_fig1_on_page(0, "Figure 1: tiny.\n\nBody text goes here eventually.")
    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00005", tmp_path)
    # page is still rendered; caption is empty since the regex's {10,500} rejected 'tiny.'
    assert out is not None
    assert out[1] == ""
