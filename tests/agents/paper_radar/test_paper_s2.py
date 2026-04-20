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
