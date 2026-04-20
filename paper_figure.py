"""Extract the Figure 1 region from an arxiv PDF as a cropped PNG + caption."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import pymupdf
import requests

logger = logging.getLogger(__name__)

_ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
_FIG1_CAPTION_RE = re.compile(r"(?:Figure|Fig\.?)\s*1[:.]\s*([^\n]{10,500})")
_CAPTION_BLOCK_RE = re.compile(r"^(?:Figure|Fig\.?)\s*1[:.]")
_DOWNLOAD_TIMEOUT = 60
_MAX_SCAN_PAGES = 5
_RENDER_DPI = 150
_CAPTION_PAD = 5            # px padding around caption in crop
_DRAWING_MIN_Y = 20         # skip page-edge decorations above this
_MAX_FIGURE_HEIGHT = 500    # a figure should start within this many px above its caption
_MIN_DRAWING_WIDTH = 20     # skip thin vertical stamps (arxiv watermark etc.)
_MIN_CROP_HEIGHT = 80


def _find_caption_block(blocks: list[tuple]) -> tuple | None:
    """Locate the text block whose content starts with 'Figure 1:' / 'Fig. 1:'."""
    for b in blocks:
        if _CAPTION_BLOCK_RE.match(b[4].strip()):
            return b
    return None


def _compute_figure_crop(
    page: "pymupdf.Page", caption_block: tuple
) -> "pymupdf.Rect":
    """Return a rect covering the figure (from drawings above caption) + the caption.

    Strategy: take the union bbox of every vector drawing and raster image whose
    ``y1 < caption_y0`` and ``y0 > _DRAWING_MIN_Y``; that's the figure region.
    Expand downward to include the caption. Span full page width to keep all
    axis labels / legends. Falls back to (top-margin → caption) when no
    drawings exist above the caption (rare — happens for figures that are a
    single embedded raster).
    """
    cap_x0, cap_y0, cap_x1, cap_y1 = caption_block[:4]
    page_rect = page.rect

    candidate_rects: list[pymupdf.Rect] = []

    def _include(r: pymupdf.Rect) -> bool:
        return (
            r.y1 < cap_y0 - 2
            and r.y0 > _DRAWING_MIN_Y
            and r.y0 > cap_y0 - _MAX_FIGURE_HEIGHT
            and r.width >= _MIN_DRAWING_WIDTH
        )

    for d in page.get_drawings():
        r = d.get("rect")
        if r is not None and _include(r):
            candidate_rects.append(r)
    for img in page.get_images(full=True):
        try:
            bbox = page.get_image_bbox(img)
        except Exception:
            continue
        if _include(bbox):
            candidate_rects.append(bbox)

    if candidate_rects:
        figure_top = min(r.y0 for r in candidate_rects) - _CAPTION_PAD
    else:
        figure_top = page_rect.y0 + 40  # top margin fallback

    return pymupdf.Rect(
        page_rect.x0,
        max(figure_top, page_rect.y0),
        page_rect.x1,
        cap_y1 + _CAPTION_PAD,
    )


def fetch_first_figure(
    arxiv_id: str, out_dir: Path | str
) -> tuple[Path, str] | None:
    """Download arxiv PDF, crop the Figure 1 region (figure + caption) as PNG.

    Caches to ``out_dir/{arxiv_id}.png`` + ``{arxiv_id}.caption.txt``. Returns
    ``(png_path, caption)`` on success, ``None`` on any failure — callers must
    not let this abort the pipeline.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{arxiv_id}.png"
    caption_path = out_dir / f"{arxiv_id}.caption.txt"

    if png_path.exists() and caption_path.exists():
        return png_path, caption_path.read_text(encoding="utf-8")

    try:
        resp = requests.get(
            _ARXIV_PDF_URL.format(arxiv_id=arxiv_id), timeout=_DOWNLOAD_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("first_figure pdf download failed for %s: %s", arxiv_id, exc)
        return None

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(resp.content)
        tmp.flush()
        try:
            doc = pymupdf.open(tmp.name)
            try:
                for pno in range(min(_MAX_SCAN_PAGES, doc.page_count)):
                    page = doc[pno]
                    blocks = page.get_text("blocks")
                    cap_block = _find_caption_block(blocks)
                    if cap_block is None:
                        continue

                    crop = _compute_figure_crop(page, cap_block)
                    if crop.height < _MIN_CROP_HEIGHT:
                        logger.info(
                            "first_figure: crop too small on page %d of %s",
                            pno + 1, arxiv_id,
                        )
                        continue

                    full_text = page.get_text()
                    caption_match = _FIG1_CAPTION_RE.search(full_text)
                    caption = caption_match.group(1).strip() if caption_match else ""

                    pix = page.get_pixmap(dpi=_RENDER_DPI, clip=crop)
                    pix.save(str(png_path))
                    caption_path.write_text(caption, encoding="utf-8")
                    return png_path, caption
            finally:
                doc.close()
        except Exception as exc:
            logger.warning("first_figure render failed for %s: %s", arxiv_id, exc)
            return None

    logger.info("first_figure: no Figure 1 found in %s", arxiv_id)
    return None
