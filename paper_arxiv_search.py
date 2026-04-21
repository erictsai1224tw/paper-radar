"""Search arxiv by abstract keyword — powers the bot's /search command.

Uses arxiv's free Atom-XML query API. Respects their published 3-second-
between-requests policy by retrying once on 429 with a short sleep.
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}
_UA = {"User-Agent": "paper-radar/1.0 (https://github.com/erictsai1224tw/paper-radar)"}
_REQUEST_TIMEOUT = 30
_RETRY_WAIT = 4  # seconds, only used once on 429
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})")


def _build_query(query: str) -> str:
    """Turn a free-text query into arxiv's search_query syntax.

    Multi-word phrase → `abs:"..." AND ti:"..."` so we match either
    abstract or title. Single token falls back to plain ``abs:``.
    """
    q = query.strip()
    if not q:
        return ""
    if " " in q:
        escaped = q.replace('"', "")
        return f'abs:"{escaped}" OR ti:"{escaped}"'
    return f"abs:{q} OR ti:{q}"


def _fetch_atom(query: str, max_results: int, *, _retried: bool = False) -> str | None:
    try:
        resp = requests.get(
            _ARXIV_API,
            params={
                "search_query": query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": max_results,
            },
            headers=_UA,
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("arxiv search request failed: %s", exc)
        return None
    if resp.status_code == 429 and not _retried:
        time.sleep(_RETRY_WAIT)
        return _fetch_atom(query, max_results, _retried=True)
    if resp.status_code != 200:
        logger.warning("arxiv search HTTP %s: %s", resp.status_code, resp.text[:100])
        return None
    return resp.text


def _parse_entries(atom_text: str) -> list[dict]:
    try:
        root = ET.fromstring(atom_text)
    except ET.ParseError as exc:
        logger.warning("arxiv atom parse failed: %s", exc)
        return []

    out: list[dict] = []
    for entry in root.findall("atom:entry", _NS):
        id_text = (entry.findtext("atom:id", default="", namespaces=_NS) or "").strip()
        m = _ARXIV_ID_RE.search(id_text)
        if not m:
            continue
        arxiv_id = m.group(1)
        title = (entry.findtext("atom:title", default="", namespaces=_NS) or "").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=_NS) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=_NS) or "").strip()
        # Collapse inline whitespace (arxiv wraps title/summary with newlines)
        title = " ".join(title.split())
        abstract = " ".join(abstract.split())
        authors = _authors(entry.findall("atom:author", _NS))
        out.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "published": published,
            "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
        })
    return out


def _authors(entries: Iterable) -> list[str]:
    names: list[str] = []
    for e in entries:
        n = e.findtext("atom:name", default="", namespaces=_NS) or ""
        n = n.strip()
        if n:
            names.append(n)
    return names


def search_arxiv(query: str, max_results: int = 5) -> list[dict]:
    """Return up to ``max_results`` recent papers matching ``query``.

    Never raises — network failures and parse errors return []. Caller
    should degrade gracefully. Each dict has: arxiv_id, title, abstract,
    authors (list), published, arxiv_url.
    """
    atom_query = _build_query(query)
    if not atom_query:
        return []
    atom_text = _fetch_atom(atom_query, max_results)
    if atom_text is None:
        return []
    return _parse_entries(atom_text)
