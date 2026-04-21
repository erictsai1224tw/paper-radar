"""Tests for paper_s2."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from paper_s2 import fetch_s2_metadata


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload or {})
    if status >= 400 and status != 404:
        r.raise_for_status.side_effect = requests.HTTPError(str(status))
    else:
        r.raise_for_status = MagicMock()
    return r


def test_returns_parsed_metadata_on_success():
    payload = {
        "venue": "NeurIPS 2024",
        "citationCount": 42,
        "influentialCitationCount": 7,
    }
    with patch("paper_s2.requests.get", return_value=_resp(200, payload)) as mock_get:
        out = fetch_s2_metadata("2501.00001")

    assert out == {
        "venue": "NeurIPS 2024",
        "citation_count": 42,
        "influential_citation_count": 7,
    }
    url = mock_get.call_args.args[0]
    assert "arXiv:2501.00001" in url


def test_returns_empty_on_404_unindexed_paper():
    with patch("paper_s2.requests.get", return_value=_resp(404)):
        assert fetch_s2_metadata("2501.99999") == {}


def test_returns_empty_on_network_error():
    with patch("paper_s2.requests.get", side_effect=requests.ConnectionError("boom")):
        assert fetch_s2_metadata("2501.00002") == {}


def test_returns_empty_on_http_500():
    with patch("paper_s2.requests.get", return_value=_resp(500, {})):
        assert fetch_s2_metadata("2501.00003") == {}


def test_null_fields_become_safe_defaults():
    payload = {"venue": None, "citationCount": None, "influentialCitationCount": None}
    with patch("paper_s2.requests.get", return_value=_resp(200, payload)):
        out = fetch_s2_metadata("2501.00004")
    assert out == {"venue": "", "citation_count": 0, "influential_citation_count": 0}


# --- fetch_recommendations --------------------------------------------------


from paper_s2 import (
    _normalize_s2_paper,
    fetch_citations,
    fetch_recommendations,
    fetch_references,
)


def _s2_paper(arxiv_id: str | None, title: str = "T", abstract: str = "A",
              authors=("Alice",)) -> dict:
    return {
        "paperId": "xyz",
        "title": title,
        "abstract": abstract,
        "authors": [{"name": a} for a in authors],
        "externalIds": ({"ArXiv": arxiv_id} if arxiv_id else {"DOI": "10.x/y"}),
    }


def test_normalize_s2_paper_valid():
    out = _normalize_s2_paper(_s2_paper("2501.00001", "Title", "Abs", ("Ada", "Babbage")))
    assert out == {
        "arxiv_id": "2501.00001",
        "title": "Title",
        "abstract": "Abs",
        "authors": ["Ada", "Babbage"],
        "arxiv_url": "https://arxiv.org/abs/2501.00001",
    }


def test_normalize_s2_paper_skips_non_arxiv():
    assert _normalize_s2_paper(_s2_paper(None)) is None


def test_fetch_recommendations_success():
    payload = {"recommendedPapers": [
        _s2_paper("2501.00001", "A", "a"),
        _s2_paper(None, "only-doi"),
        _s2_paper("2501.00002", "B", "b"),
    ]}
    with patch("paper_s2.requests.get", return_value=_resp(200, payload)) as mock_get:
        out = fetch_recommendations("2604.16044", limit=3)
    assert [p["arxiv_id"] for p in out] == ["2501.00001", "2501.00002"]
    assert "ARXIV:2604.16044" in mock_get.call_args.args[0]


def test_fetch_recommendations_empty_arxiv_id():
    with patch("paper_s2.requests.get") as mock_get:
        assert fetch_recommendations("") == []
    assert mock_get.call_count == 0


def test_fetch_recommendations_404_returns_empty():
    with patch("paper_s2.requests.get", return_value=_resp(404)):
        assert fetch_recommendations("2604.99999") == []


def test_fetch_recommendations_network_error_returns_empty():
    with patch("paper_s2.requests.get", side_effect=requests.ConnectionError("boom")):
        assert fetch_recommendations("2604.16044") == []


# --- fetch_references / fetch_citations -------------------------------------


def test_fetch_references_parses_cited_paper_embed():
    payload = {"data": [
        {"citedPaper": _s2_paper("2401.00001", "ref1")},
        {"citedPaper": _s2_paper(None, "no-arxiv-ref")},
        {"citedPaper": _s2_paper("2401.00002", "ref2")},
    ]}
    with patch("paper_s2.requests.get", return_value=_resp(200, payload)):
        out = fetch_references("2604.16044", limit=5)
    assert [p["arxiv_id"] for p in out] == ["2401.00001", "2401.00002"]


def test_fetch_citations_parses_citing_paper_embed():
    payload = {"data": [
        {"citingPaper": _s2_paper("2605.00001", "cite1")},
    ]}
    with patch("paper_s2.requests.get", return_value=_resp(200, payload)):
        out = fetch_citations("2604.16044", limit=5)
    assert [p["arxiv_id"] for p in out] == ["2605.00001"]


def test_fetch_references_missing_inner_entry_skipped():
    payload = {"data": [
        {"citedPaper": None},
        {"somethingElse": _s2_paper("2401.00001")},
        {"citedPaper": _s2_paper("2401.00002")},
    ]}
    with patch("paper_s2.requests.get", return_value=_resp(200, payload)):
        out = fetch_references("2604.16044")
    assert [p["arxiv_id"] for p in out] == ["2401.00002"]


def test_graph_fetch_network_error_returns_empty():
    with patch("paper_s2.requests.get", side_effect=requests.ConnectionError("boom")):
        assert fetch_references("2604.16044") == []
        assert fetch_citations("2604.16044") == []
