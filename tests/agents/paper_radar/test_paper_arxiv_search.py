"""Tests for paper_arxiv_search."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from paper_arxiv_search import _build_query, _parse_entries, search_arxiv


_SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2604.16044v1</id>
    <title>  Elucidating the SNR-t Bias
      of Diffusion Models  </title>
    <summary>We identify a bias in DDPMs where SNR diverges from t during inference. We propose a frequency-domain correction that improves FID significantly.</summary>
    <published>2026-04-20T10:30:00Z</published>
    <author><name>Alice Chen</name></author>
    <author><name>Bob Wu</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2604.12345v2</id>
    <title>Another Paper</title>
    <summary>Summary 2</summary>
    <published>2026-04-19T08:00:00Z</published>
    <author><name>Carol</name></author>
  </entry>
</feed>
"""


def _resp(status: int, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def test_build_query_single_word():
    assert _build_query("diffusion") == "abs:diffusion OR ti:diffusion"


def test_build_query_multi_word_phrase():
    assert _build_query("efficient diffusion sampling") == 'abs:"efficient diffusion sampling" OR ti:"efficient diffusion sampling"'


def test_build_query_strips_quotes_from_input():
    out = _build_query('"rl" agents')
    assert '"' not in out.replace('abs:"rl agents" OR ti:"rl agents"', "")


def test_build_query_empty_returns_empty():
    assert _build_query("   ") == ""


def test_parse_entries_extracts_fields():
    entries = _parse_entries(_SAMPLE_ATOM)
    assert len(entries) == 2
    e = entries[0]
    assert e["arxiv_id"] == "2604.16044"
    # whitespace-collapsed title
    assert e["title"] == "Elucidating the SNR-t Bias of Diffusion Models"
    assert "SNR diverges" in e["abstract"]
    assert e["authors"] == ["Alice Chen", "Bob Wu"]
    assert e["published"].startswith("2026-04-20")
    assert e["arxiv_url"] == "https://arxiv.org/abs/2604.16044"


def test_parse_entries_handles_empty_feed():
    assert _parse_entries("<feed xmlns='http://www.w3.org/2005/Atom'></feed>") == []


def test_parse_entries_handles_malformed_xml():
    assert _parse_entries("not xml at all") == []


def test_search_arxiv_happy_path():
    with patch("paper_arxiv_search.requests.get", return_value=_resp(200, _SAMPLE_ATOM)) as mock_get:
        out = search_arxiv("efficient diffusion", max_results=5)
    assert len(out) == 2
    assert out[0]["arxiv_id"] == "2604.16044"
    params = mock_get.call_args.kwargs["params"]
    assert params["max_results"] == 5
    assert params["sortBy"] == "submittedDate"
    assert 'abs:"efficient diffusion"' in params["search_query"]


def test_search_arxiv_empty_query_returns_empty():
    with patch("paper_arxiv_search.requests.get") as mock_get:
        assert search_arxiv("   ") == []
    assert mock_get.call_count == 0


def test_search_arxiv_network_error_returns_empty():
    with patch("paper_arxiv_search.requests.get", side_effect=requests.ConnectionError("boom")):
        assert search_arxiv("topic") == []


def test_search_arxiv_retries_once_on_429():
    calls = [0]
    def fake_get(*a, **kw):
        calls[0] += 1
        if calls[0] == 1:
            return _resp(429, "Rate exceeded.")
        return _resp(200, _SAMPLE_ATOM)

    with patch("paper_arxiv_search.requests.get", side_effect=fake_get), \
         patch("paper_arxiv_search.time.sleep"):
        out = search_arxiv("topic")
    assert calls[0] == 2
    assert len(out) == 2


def test_search_arxiv_gives_up_on_second_429():
    with patch("paper_arxiv_search.requests.get", return_value=_resp(429, "Rate exceeded.")), \
         patch("paper_arxiv_search.time.sleep"):
        assert search_arxiv("topic") == []


def test_search_arxiv_skips_entries_without_parseable_id():
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://broken/url</id><title>x</title></entry>
      <entry><id>http://arxiv.org/abs/2501.00001v1</id><title>good</title><summary>s</summary></entry>
    </feed>"""
    assert [e["arxiv_id"] for e in _parse_entries(atom)] == ["2501.00001"]
