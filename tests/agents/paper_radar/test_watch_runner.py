"""Tests for watch_runner."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from watch_db import get_seen_for_watch, init_watch_db, upsert_watch
from watch_runner import run_all_watches, run_one_watch


def _sample_papers(ids: list[str]) -> list[dict]:
    return [{
        "arxiv_id": i,
        "title": f"Paper {i}",
        "abstract": "abs",
        "authors": ["Ada"],
        "published": "2026-04-20T10:00:00Z",
        "arxiv_url": f"https://arxiv.org/abs/{i}",
    } for i in ids]


def test_run_one_watch_pushes_new_and_marks_seen(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "reinforcement learning")
    watch = {"name": "rl", "query": "reinforcement learning"}

    sent: list[str] = []

    def fake_send(token, chat_id, text, **kw):
        sent.append(text)

    with patch("watch_runner.paper_arxiv_search.search_arxiv",
               return_value=_sample_papers(["2401.00001", "2401.00002"])), \
         patch("watch_runner.send_message", side_effect=fake_send), \
         patch("watch_runner.time.sleep"):
        pushed = run_one_watch(watch, tmp_db, "tok", "chat42")

    assert pushed == 2
    # 1 header + 2 results
    assert len(sent) == 3
    assert "watch" in sent[0]
    assert get_seen_for_watch(tmp_db, "rl") == {"2401.00001", "2401.00002"}


def test_run_one_watch_skips_already_seen(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "q")
    # already seen once
    from watch_db import mark_seen_for_watch
    mark_seen_for_watch(tmp_db, "rl", ["2401.00001"])
    watch = {"name": "rl", "query": "q"}

    sent: list[str] = []

    def fake_send(token, chat_id, text, **kw):
        sent.append(text)

    with patch("watch_runner.paper_arxiv_search.search_arxiv",
               return_value=_sample_papers(["2401.00001", "2401.00002"])), \
         patch("watch_runner.send_message", side_effect=fake_send), \
         patch("watch_runner.time.sleep"):
        pushed = run_one_watch(watch, tmp_db, "tok", "chat42")

    assert pushed == 1
    assert get_seen_for_watch(tmp_db, "rl") == {"2401.00001", "2401.00002"}


def test_run_one_watch_empty_arxiv_response_returns_zero(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "q")
    watch = {"name": "rl", "query": "q"}

    with patch("watch_runner.paper_arxiv_search.search_arxiv", return_value=[]), \
         patch("watch_runner.send_message") as mock_send:
        pushed = run_one_watch(watch, tmp_db, "tok", "chat42")
    assert pushed == 0
    assert mock_send.call_count == 0


def test_run_all_watches_iterates_each_and_totals_new(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "q1")
    upsert_watch(tmp_db, "cv", "q2")

    def fake_search(q, max_results):
        return _sample_papers(["2401.00001"] if q == "q1" else ["2401.00002", "2401.00003"])

    with patch("watch_runner.paper_arxiv_search.search_arxiv", side_effect=fake_search), \
         patch("watch_runner.send_message"), \
         patch("watch_runner.time.sleep"):
        total = run_all_watches(tmp_db, "tok", "chat42")

    assert total == 3  # 1 + 2


def test_run_all_watches_survives_one_crashing(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "good", "q1")
    upsert_watch(tmp_db, "bad", "q2")

    def fake_search(q, max_results):
        if q == "q2":
            raise RuntimeError("boom")
        return _sample_papers(["2401.00001"])

    with patch("watch_runner.paper_arxiv_search.search_arxiv", side_effect=fake_search), \
         patch("watch_runner.send_message"), \
         patch("watch_runner.time.sleep"):
        total = run_all_watches(tmp_db, "tok", "chat42")
    # 'good' still succeeded
    assert total == 1
