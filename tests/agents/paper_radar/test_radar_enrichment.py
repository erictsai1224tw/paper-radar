"""Tests for new enrichment helpers on radar.py (authors, watchlist, message build)."""
from __future__ import annotations

import pytest

from radar import _build_paper_message, _normalize, is_watched, load_watchlist


def test_normalize_extracts_authors_and_github():
    item = {
        "paper": {
            "id": "2501.00001",
            "title": "Cool Paper",
            "summary": "abstract text",
            "upvotes": 42,
            "authors": [
                {"name": "Alice Chen"},
                {"name": "Bob Smith"},
                {"other": "no name here"},  # malformed entry should be skipped
            ],
            "githubRepo": "https://github.com/foo/bar",
            "githubStars": 123,
        },
    }
    out = _normalize(item)
    assert out["authors"] == ["Alice Chen", "Bob Smith"]
    assert out["github_url"] == "https://github.com/foo/bar"
    assert out["github_stars"] == 123


def test_normalize_handles_missing_optional_fields():
    item = {"paper": {"id": "2501.00002", "title": "No Extras", "summary": "x", "upvotes": 1}}
    out = _normalize(item)
    assert out["authors"] == []
    assert out["github_url"] == ""
    assert out["github_stars"] == 0


def test_load_watchlist_lowercases_and_strips(monkeypatch):
    monkeypatch.setenv("AUTHOR_WATCHLIST", "Karpathy, DeepMind , Yann LeCun")
    assert load_watchlist() == ["karpathy", "deepmind", "yann lecun"]


def test_load_watchlist_empty_when_unset(monkeypatch):
    monkeypatch.delenv("AUTHOR_WATCHLIST", raising=False)
    assert load_watchlist() == []


@pytest.mark.parametrize(
    "authors,watchlist,expected",
    [
        (["Alice", "Andrej Karpathy"], ["karpathy"], True),
        (["Alice", "Bob"], ["karpathy"], False),
        (["Yann LeCun"], ["yann lecun"], True),
        (["y. lecun"], ["yann lecun"], False),  # watchlist is substring, not fuzzy
        ([], ["karpathy"], False),
        (["Alice"], [], False),
    ],
)
def test_is_watched(authors, watchlist, expected):
    assert is_watched(authors, watchlist) is expected


def test_build_paper_message_shows_star_when_watched():
    paper = {
        "title": "Paper Title",
        "tldr": "tldr content",
        "tags": [],
        "upvotes": 5,
        "year": 2025,
        "arxiv_url": "https://arxiv.org/abs/2501.1",
        "watched": True,
    }
    msg = _build_paper_message(1, paper)
    assert msg.startswith("<b>⭐ 1. Paper Title</b>")


def test_build_paper_message_no_star_when_not_watched():
    paper = {
        "title": "Paper Title", "tldr": "x", "tags": [],
        "upvotes": 1, "year": 2025, "arxiv_url": "https://arxiv.org/abs/x",
        "watched": False,
    }
    assert _build_paper_message(1, paper).startswith("<b>1. Paper Title</b>")


def test_build_paper_message_shows_code_link_when_github_url_present():
    paper = {
        "title": "P", "tldr": "x", "tags": [], "upvotes": 0, "year": 2025,
        "arxiv_url": "https://arxiv.org/abs/x",
        "github_url": "https://github.com/a/b",
    }
    msg = _build_paper_message(1, paper)
    assert 'href="https://github.com/a/b"' in msg
    assert "code" in msg


def test_build_paper_message_renders_citation_badge():
    paper = {
        "title": "P", "tldr": "x", "tags": [], "upvotes": 0, "year": 2025,
        "arxiv_url": "https://arxiv.org/abs/x",
        "citation_count": 42, "influential_citation_count": 5,
    }
    msg = _build_paper_message(1, paper)
    assert "📎 42 cites" in msg
    assert "5✨" in msg


def test_build_paper_message_omits_citation_when_zero():
    paper = {
        "title": "P", "tldr": "x", "tags": [], "upvotes": 0, "year": 2025,
        "arxiv_url": "https://arxiv.org/abs/x",
        "citation_count": 0, "influential_citation_count": 0,
    }
    assert "cites" not in _build_paper_message(1, paper)
