"""Tests for rerank."""
from __future__ import annotations

from pathlib import Path

from feedback_db import init_feedback_db, record_feedback
from rerank import (
    _tag_like_rates,
    rerank_by_preference_with_archive,
    score_paper,
)


def test_tag_rates_with_clean_signal():
    feedback = [
        {"arxiv_id": "a", "action": "like",    "user_id": "1", "created_at": "x"},
        {"arxiv_id": "b", "action": "like",    "user_id": "1", "created_at": "x"},
        {"arxiv_id": "c", "action": "dislike", "user_id": "1", "created_at": "x"},
    ]
    lookup = {"a": ["rl"], "b": ["rl"], "c": ["tabular"]}
    rates = _tag_like_rates(feedback, lookup)
    # rl: 2 likes, 0 dislikes → (2+1)/(2+0+2) = 3/4 = 0.75
    # tabular: 0 likes, 1 dislike → (0+1)/(0+1+2) = 1/3 ≈ 0.333
    assert rates["rl"] == 0.75
    assert abs(rates["tabular"] - 1/3) < 0.01


def test_tag_rates_ignores_save_action():
    feedback = [
        {"arxiv_id": "a", "action": "like", "user_id": "1", "created_at": "x"},
        {"arxiv_id": "b", "action": "save", "user_id": "1", "created_at": "x"},
    ]
    lookup = {"a": ["rl"], "b": ["rl"]}
    rates = _tag_like_rates(feedback, lookup)
    # save is not used in training — only 1 like counted
    assert rates["rl"] == (1 + 1) / (1 + 0 + 2)


def test_score_paper_averages_known_tag_rates():
    rates = {"rl": 0.8, "vision": 0.2}
    paper = {"tags": ["rl", "vision"]}
    assert score_paper(paper, rates) == 0.5


def test_score_paper_ignores_unknown_tags():
    rates = {"rl": 0.8}
    paper = {"tags": ["rl", "new-tag"]}
    assert score_paper(paper, rates) == 0.8


def test_score_paper_neutral_when_no_tag_matches():
    rates = {"rl": 0.8}
    paper = {"tags": ["nope"]}
    assert score_paper(paper, rates) == 0.5


def test_score_paper_neutral_when_no_tags():
    rates = {"rl": 0.8}
    assert score_paper({"tags": []}, rates) == 0.5


def test_rerank_does_nothing_below_min_samples(tmp_db: Path):
    init_feedback_db(tmp_db)
    record_feedback(tmp_db, "a", "like", "1")
    record_feedback(tmp_db, "b", "dislike", "1")

    papers = [
        {"arxiv_id": "new1", "tags": ["rl"]},
        {"arxiv_id": "new2", "tags": ["tabular"]},
    ]
    result = rerank_by_preference_with_archive(
        papers, tmp_db, {"a": ["rl"], "b": ["tabular"]}, min_samples=10,
    )
    # unchanged — only 2 samples
    assert [p["arxiv_id"] for p in result] == ["new1", "new2"]


def test_rerank_reorders_by_tag_preference(tmp_db: Path):
    init_feedback_db(tmp_db)
    # 10 likes on "rl" tag, 10 dislikes on "tabular" tag
    for i in range(10):
        record_feedback(tmp_db, f"rl{i}",  "like",    "1")
        record_feedback(tmp_db, f"tab{i}", "dislike", "1")
    archive = {
        **{f"rl{i}":  ["rl"]      for i in range(10)},
        **{f"tab{i}": ["tabular"] for i in range(10)},
    }

    # Input order deliberately puts tabular first
    papers = [
        {"arxiv_id": "new_tab", "tags": ["tabular"]},
        {"arxiv_id": "new_rl",  "tags": ["rl"]},
    ]
    result = rerank_by_preference_with_archive(papers, tmp_db, archive, min_samples=5)
    assert [p["arxiv_id"] for p in result] == ["new_rl", "new_tab"]
