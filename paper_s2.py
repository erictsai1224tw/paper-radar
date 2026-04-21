"""Fetch paper metadata from Semantic Scholar (venue, citations)."""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_S2_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
_S2_RECOMMEND_URL = (
    "https://api.semanticscholar.org/recommendations/v1/papers/forpaper/ARXIV:{arxiv_id}"
)
_S2_REFS_URL = "https://api.semanticscholar.org/graph/v1/paper/ARXIV:{arxiv_id}/references"
_S2_CITES_URL = "https://api.semanticscholar.org/graph/v1/paper/ARXIV:{arxiv_id}/citations"
_FIELDS = "venue,year,citationCount,influentialCitationCount,externalIds"
_PAPER_FIELDS = "title,abstract,authors,externalIds"
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


def _normalize_s2_paper(p: dict) -> dict | None:
    """Turn an S2 paper dict into our search-result shape. None if no arxiv_id."""
    external_ids = p.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv") or external_ids.get("arxiv")
    if not arxiv_id:
        return None
    authors = [
        a.get("name", "").strip()
        for a in (p.get("authors") or [])
        if isinstance(a, dict) and a.get("name")
    ]
    return {
        "arxiv_id": arxiv_id,
        "title": (p.get("title") or "").strip(),
        "abstract": (p.get("abstract") or "").strip(),
        "authors": authors,
        "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def fetch_recommendations(arxiv_id: str, limit: int = 5) -> list[dict]:
    """Return up to ``limit`` S2-recommended papers similar to ``arxiv_id``.

    Normalized dicts with: arxiv_id, title, abstract, authors, arxiv_url.
    Papers without an ArXiv external id are skipped (can't deep-link). Fails
    soft on any error.
    """
    if not arxiv_id:
        return []
    try:
        resp = requests.get(
            _S2_RECOMMEND_URL.format(arxiv_id=arxiv_id),
            params={"fields": _PAPER_FIELDS, "limit": limit},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("s2 recs request failed for %s: %s", arxiv_id, exc)
        return []
    if resp.status_code == 404:
        logger.info("s2 recs: %s not indexed", arxiv_id)
        return []
    try:
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("s2 recs parse failed for %s: %s", arxiv_id, exc)
        return []
    out: list[dict] = []
    for p in data.get("recommendedPapers") or []:
        n = _normalize_s2_paper(p)
        if n:
            out.append(n)
    return out


def _fetch_graph_neighbours(
    arxiv_id: str, url_template: str, embed_key: str, limit: int
) -> list[dict]:
    if not arxiv_id:
        return []
    try:
        resp = requests.get(
            url_template.format(arxiv_id=arxiv_id),
            params={"fields": _PAPER_FIELDS, "limit": limit},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("s2 graph request failed for %s: %s", arxiv_id, exc)
        return []
    if resp.status_code == 404:
        return []
    try:
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("s2 graph parse failed for %s: %s", arxiv_id, exc)
        return []
    out: list[dict] = []
    for entry in data.get("data") or []:
        inner = entry.get(embed_key)
        if not isinstance(inner, dict):
            continue
        n = _normalize_s2_paper(inner)
        if n:
            out.append(n)
    return out


def fetch_references(arxiv_id: str, limit: int = 5) -> list[dict]:
    """Papers that the given arxiv paper cites (S2 '/references')."""
    return _fetch_graph_neighbours(arxiv_id, _S2_REFS_URL, "citedPaper", limit)


def fetch_citations(arxiv_id: str, limit: int = 5) -> list[dict]:
    """Papers citing the given arxiv paper (S2 '/citations')."""
    return _fetch_graph_neighbours(arxiv_id, _S2_CITES_URL, "citingPaper", limit)
