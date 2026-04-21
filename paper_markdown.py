"""Download arxiv PDFs and convert to markdown via markitdown for deeper bot context."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import requests
from markitdown import MarkItDown

logger = logging.getLogger(__name__)

_ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
_DOWNLOAD_TIMEOUT = 60

# markitdown's PDF converter occasionally leaks binary control bytes into its
# text output — null bytes break subprocess argv (ValueError: embedded null
# byte), other C0 control chars look like garbage in prompts. Strip everything
# in \x00..\x1f except tab / LF / CR.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_markdown(text: str) -> str:
    return _CONTROL_CHAR_RE.sub("", text)


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

    out_path.write_text(_sanitize_markdown(result.text_content), encoding="utf-8")
    return out_path
