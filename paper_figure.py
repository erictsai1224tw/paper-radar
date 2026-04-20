"""Extract the page containing 'Figure 1' from an arxiv PDF as a PNG + caption."""
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
_FIG1_MARKER_RE = re.compile(r"(?:Figure|Fig\.?)\s*1[:.]")
_DOWNLOAD_TIMEOUT = 60
_MAX_SCAN_PAGES = 5
_RENDER_DPI = 150


def fetch_first_figure(
    arxiv_id: str, out_dir: Path | str
) -> tuple[Path, str] | None:
    """Download arxiv PDF, render the page containing Figure 1, extract caption.

    Caches to ``out_dir/{arxiv_id}.png`` + ``{arxiv_id}.caption.txt``. Returns
    ``(png_path, caption)`` on success, ``None`` otherwise — the caller should
    not let this abort the rest of the pipeline.
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
                    text = page.get_text()
                    if not _FIG1_MARKER_RE.search(text):
                        continue
                    caption_match = _FIG1_CAPTION_RE.search(text)
                    caption = caption_match.group(1).strip() if caption_match else ""
                    pix = page.get_pixmap(dpi=_RENDER_DPI)
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
