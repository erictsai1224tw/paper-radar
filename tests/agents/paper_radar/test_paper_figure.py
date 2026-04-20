"""Tests for paper_figure."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
import requests

from paper_figure import fetch_first_figure


def _mock_resp(content: bytes = b"%PDF-fake") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def _mk_page(
    caption_block: tuple | None,
    other_blocks: list[tuple] = (),
    drawing_rects: list[pymupdf.Rect] = (),
    page_rect: pymupdf.Rect = pymupdf.Rect(0, 0, 612, 792),
    full_text: str = "",
) -> MagicMock:
    """Construct a mock pymupdf.Page with configurable caption/drawings."""
    page = MagicMock()
    page.rect = page_rect
    blocks = list(other_blocks)
    if caption_block is not None:
        blocks.append(caption_block)

    def _get_text(mode: str | None = None):
        if mode == "blocks":
            return blocks
        return full_text or (caption_block[4] if caption_block else "")

    page.get_text.side_effect = _get_text
    page.get_drawings.return_value = [{"rect": r} for r in drawing_rects]
    page.get_images.return_value = []
    pix = MagicMock()
    pix.save = MagicMock()
    page.get_pixmap.return_value = pix
    return page


def _mk_doc(pages: list[MagicMock]) -> MagicMock:
    doc = MagicMock()
    doc.page_count = len(pages)
    doc.__getitem__.side_effect = lambda i: pages[i]
    doc.close = MagicMock()
    return doc


def test_fetch_returns_existing_cache(tmp_path: Path):
    (tmp_path / "2501.00001.png").write_bytes(b"\x89PNG cached")
    (tmp_path / "2501.00001.caption.txt").write_text("cached caption", encoding="utf-8")
    with patch("paper_figure.requests.get") as mock_get:
        out = fetch_first_figure("2501.00001", tmp_path)
    assert mock_get.call_count == 0
    assert out == (tmp_path / "2501.00001.png", "cached caption")


def test_fetch_crops_figure_region_above_caption(tmp_path: Path):
    caption = (
        50, 200, 550, 260,
        "Figure 1: overview of XYZ method that does cool stuff.",
        0, 0,
    )
    drawings = [
        pymupdf.Rect(60, 80, 540, 150),
        pymupdf.Rect(70, 160, 530, 190),
    ]
    page = _mk_page(caption, drawing_rects=drawings)
    doc = _mk_doc([page])

    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00002", tmp_path)

    assert out is not None
    png_path, caption_text = out
    assert png_path == tmp_path / "2501.00002.png"
    assert caption_text == "overview of XYZ method that does cool stuff."

    clip = page.get_pixmap.call_args.kwargs["clip"]
    # crop covers figure top (drawings min y=80) and caption bottom (y=260)
    assert clip.y0 <= 75  # up to 5px pad above drawings
    assert clip.y1 >= 260
    # full width
    assert clip.x0 == 0
    assert clip.x1 == 612


def test_fetch_falls_back_to_top_margin_when_no_drawings(tmp_path: Path):
    caption = (50, 300, 550, 360, "Figure 1: something short that's at least 10 chars", 0, 0)
    page = _mk_page(caption, drawing_rects=[])
    doc = _mk_doc([page])

    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00003", tmp_path)

    assert out is not None
    clip = page.get_pixmap.call_args.kwargs["clip"]
    assert 30 <= clip.y0 <= 50  # hit the 40px top-margin fallback
    assert clip.y1 >= 360


def test_fetch_skips_drawings_at_page_edge(tmp_path: Path):
    caption = (50, 200, 550, 260, "Figure 1: test fig description here.", 0, 0)
    drawings = [
        pymupdf.Rect(0, 5, 612, 12),       # header decoration, should be filtered
        pymupdf.Rect(60, 80, 540, 180),    # real figure
    ]
    page = _mk_page(caption, drawing_rects=drawings)
    doc = _mk_doc([page])

    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        fetch_first_figure("2501.00004", tmp_path)

    clip = page.get_pixmap.call_args.kwargs["clip"]
    # Should be around real figure top (y=80), not page edge (y=5)
    assert 70 <= clip.y0 <= 85


def test_fetch_returns_none_when_no_figure_1_block(tmp_path: Path):
    page = _mk_page(caption_block=None, other_blocks=[
        (50, 100, 550, 200, "body text, no figure mentioned", 0, 0),
    ])
    doc = _mk_doc([page, page, page])

    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00005", tmp_path)
    assert out is None


def test_fetch_accepts_fig_dot_variant(tmp_path: Path):
    caption = (50, 200, 550, 240, "Fig. 1: short caption here for testing.", 0, 0)
    drawings = [pymupdf.Rect(60, 80, 540, 180)]
    page = _mk_page(caption, drawing_rects=drawings)
    doc = _mk_doc([page])

    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00006", tmp_path)
    assert out is not None
    assert out[1] == "short caption here for testing."


def test_fetch_returns_none_on_http_error(tmp_path: Path):
    resp = _mock_resp()
    resp.raise_for_status.side_effect = requests.HTTPError("404")
    with patch("paper_figure.requests.get", return_value=resp):
        out = fetch_first_figure("bad-id", tmp_path)
    assert out is None


def test_fetch_skips_page_when_crop_too_small(tmp_path: Path):
    # Caption block exists but there are no drawings AND caption is very close to top.
    # fallback upper=40, caption_y1=60 → height=20 < 80 → skip this page.
    caption = (50, 50, 550, 60, "Figure 1: tiny region (mention in header).", 0, 0)
    page_small = _mk_page(caption, drawing_rects=[])
    # Second page: proper figure
    caption2 = (50, 400, 550, 460, "Figure 1: actual method overview here.", 0, 0)
    drawings2 = [pymupdf.Rect(60, 100, 540, 380)]
    page_real = _mk_page(caption2, drawing_rects=drawings2)

    doc = _mk_doc([page_small, page_real])
    with patch("paper_figure.requests.get", return_value=_mock_resp()), \
         patch("paper_figure.pymupdf.open", return_value=doc):
        out = fetch_first_figure("2501.00007", tmp_path)
    assert out is not None
    assert out[1] == "actual method overview here."
    # page_real's pixmap should have been called, not page_small's
    assert page_real.get_pixmap.called
    assert not page_small.get_pixmap.called
