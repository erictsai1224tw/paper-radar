"""Tests for radar.rank_by_interest."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from radar import rank_by_interest


def _papers(ids: list[str]) -> list[dict]:
    return [{"arxiv_id": i, "title": f"T{i}", "tldr": f"tldr{i}", "tags": []} for i in ids]


def _proc(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_no_interest_returns_top_n_unchanged():
    papers = _papers(["a", "b", "c", "d"])
    assert [p["arxiv_id"] for p in rank_by_interest(papers, "", top_n=2)] == ["a", "b"]


def test_empty_papers_returns_empty():
    assert rank_by_interest([], "some interest", top_n=5) == []


def test_llm_ranking_reorders_to_match_response():
    papers = _papers(["a", "b", "c", "d"])
    outer = json.dumps({"result": json.dumps({"ordered_arxiv_ids": ["c", "a"]})})
    with patch("radar.subprocess.run", return_value=_proc(outer)):
        out = rank_by_interest(papers, "prefer c > a", top_n=3, provider="claude")
    assert [p["arxiv_id"] for p in out] == ["c", "a"]


def test_llm_response_missing_ids_are_ignored():
    papers = _papers(["a", "b"])
    outer = json.dumps({"result": json.dumps({"ordered_arxiv_ids": ["a", "unknown-id", "b"]})})
    with patch("radar.subprocess.run", return_value=_proc(outer)):
        out = rank_by_interest(papers, "x", top_n=5, provider="claude")
    assert [p["arxiv_id"] for p in out] == ["a", "b"]


def test_llm_failure_falls_back_to_top_n_order():
    papers = _papers(["a", "b", "c"])
    with patch("radar.subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "claude")):
        out = rank_by_interest(papers, "x", top_n=2, provider="claude")
    assert [p["arxiv_id"] for p in out] == ["a", "b"]


def test_llm_empty_ordered_falls_back_to_top_n():
    papers = _papers(["a", "b", "c"])
    outer = json.dumps({"result": json.dumps({"ordered_arxiv_ids": []})})
    with patch("radar.subprocess.run", return_value=_proc(outer)):
        out = rank_by_interest(papers, "x", top_n=2, provider="claude")
    assert [p["arxiv_id"] for p in out] == ["a", "b"]


def test_top_n_caps_llm_output():
    papers = _papers(["a", "b", "c", "d"])
    outer = json.dumps({"result": json.dumps({"ordered_arxiv_ids": ["d", "c", "b", "a"]})})
    with patch("radar.subprocess.run", return_value=_proc(outer)):
        out = rank_by_interest(papers, "x", top_n=2, provider="claude")
    assert [p["arxiv_id"] for p in out] == ["d", "c"]
