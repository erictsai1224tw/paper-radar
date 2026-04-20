"""Download arxiv PDFs and convert to markdown via markitdown for deeper bot context."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import requests
from markitdown import MarkItDown

logger = logging.getLogger(__name__)

_ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
_DOWNLOAD_TIMEOUT = 60


def fetch_pdf_as_markdown(arxiv_id: str, out_dir: Path | str) -> Path | None:
    """Download the arxiv PDF for ``arxiv_id`` and convert it to markdown.

    Caches to ``out_dir/{arxiv_id}.md`` — returns the cached path if present.
    Returns ``None`` (and logs a warning) on any failure — callers should not
    let paper-markdown failures abort the rest of the pipeline.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{arxiv_id}.md"
    if out_path.exists():
        return out_path

    try:
        resp = requests.get(
            _ARXIV_PDF_URL.format(arxiv_id=arxiv_id), timeout=_DOWNLOAD_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("pdf download failed for %s: %s", arxiv_id, exc)
        return None

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(resp.content)
        tmp.flush()
        try:
            result = MarkItDown().convert(tmp.name)
        except Exception as exc:
            logger.warning("markitdown conversion failed for %s: %s", arxiv_id, exc)
            return None

    out_path.write_text(result.text_content, encoding="utf-8")
    return out_path
