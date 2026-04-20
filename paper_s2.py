"""Fetch paper metadata from Semantic Scholar (venue, citations)."""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_S2_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
_FIELDS = "venue,year,citationCount,influentialCitationCount,externalIds"
_TIMEOUT = 15


def fetch_s2_metadata(arxiv_id: str) -> dict:
    """Return {venue, citation_count, influential_citation_count} or empty dict.

    Never raises. 404 (paper not yet indexed) and other errors log and return {}.
    Free tier: 100 requests per 5 min per IP — enough for 8 papers/day.
    """
    try:
        resp = requests.get(
            _S2_URL.format(arxiv_id=arxiv_id),
            params={"fields": _FIELDS},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("s2 fetch failed for %s: %s", arxiv_id, exc)
        return {}
    if resp.status_code == 404:
        logger.info("s2: paper %s not yet indexed", arxiv_id)
        return {}
    try:
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("s2 parse failed for %s: %s", arxiv_id, exc)
        return {}
    return {
        "venue": data.get("venue") or "",
        "citation_count": int(data.get("citationCount") or 0),
        "influential_citation_count": int(data.get("influentialCitationCount") or 0),
    }
