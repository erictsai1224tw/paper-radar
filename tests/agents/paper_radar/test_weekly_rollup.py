"""Tests for weekly_rollup."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from weekly_rollup import (
    _build_cluster_prompt,
    archive_papers,
    build_rollup_message,
    cluster_papers,
    load_recent_papers,
)


def test_archive_appends_jsonl_with_timestamp(tmp_path: Path):
    archive = tmp_path / "a.jsonl"
    archive_papers(
        [
            {"arxiv_id": "x1", "title": "T1", "tldr": "tl1", "tags": ["a"]},
            {"arxiv_id": "x2", "title": "T2", "tldr": "tl2", "tags": ["b"]},
        ],
        archive,
    )
    lines = archive.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for ln in lines:
        d = json.loads(ln)
        assert "archived_at" in d
        # ISO format, parseable
        datetime.fromisoformat(d["archived_at"])


def test_archive_appends_without_overwriting(tmp_path: Path):
    archive = tmp_path / "a.jsonl"
    archive_papers([{"arxiv_id": "x1", "title": "T1"}], archive)
    archive_papers([{"arxiv_id": "x2", "title": "T2"}], archive)
    assert len(archive.read_text().splitlines()) == 2


def test_load_recent_filters_by_date(tmp_path: Path):
    archive = tmp_path / "a.jsonl"
    now = datetime.now()
    old = (now - timedelta(days=10)).isoformat()
    fresh = (now - timedelta(days=2)).isoformat()
    with archive.open("w") as fp:
        fp.write(json.dumps({"arxiv_id": "old", "archived_at": old}) + "\n")
        fp.write(json.dumps({"arxiv_id": "fresh", "archived_at": fresh}) + "\n")

    recent = load_recent_papers(archive, days=7, now=now)
    assert [p["arxiv_id"] for p in recent] == ["fresh"]


def test_load_recent_handles_missing_file(tmp_path: Path):
    assert load_recent_papers(tmp_path / "nope.jsonl", days=7) == []


def test_load_recent_skips_malformed_lines(tmp_path: Path):
    archive = tmp_path / "a.jsonl"
    now = datetime.now()
    fresh = (now - timedelta(hours=1)).isoformat()
    archive.write_text(
        "not json\n"
        + json.dumps({"arxiv_id": "valid", "archived_at": fresh}) + "\n"
        + json.dumps({"arxiv_id": "no_ts"}) + "\n"      # missing archived_at
        + json.dumps({"arxiv_id": "bad_ts", "archived_at": "not-a-date"}) + "\n",
        encoding="utf-8",
    )
    recent = load_recent_papers(archive, days=7, now=now)
    assert [p["arxiv_id"] for p in recent] == ["valid"]


def test_build_cluster_prompt_lists_each_paper_numbered():
    papers = [
        {"arxiv_id": "2501.1", "title": "P A", "tldr": "a tldr", "tags": ["llm"]},
        {"arxiv_id": "2501.2", "title": "P B", "tldr": "b tldr", "tags": []},
    ]
    p = _build_cluster_prompt(papers)
    assert '1. [2501.1] "P A"' in p
    assert '2. [2501.2] "P B"' in p
    assert "a tldr" in p


def test_cluster_papers_parses_claude_json():
    fake_stdout = json.dumps({"result": json.dumps({
        "clusters": [{"theme": "X", "summary": "s", "arxiv_ids": ["2501.1"]}],
    })})
    proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_stdout, stderr="")
    with patch("weekly_rollup.subprocess.run", return_value=proc):
        out = cluster_papers([{"arxiv_id": "2501.1", "title": "x", "tldr": "y", "tags": []}])
    assert out == [{"theme": "X", "summary": "s", "arxiv_ids": ["2501.1"]}]


def test_cluster_papers_falls_back_on_subprocess_error():
    with patch("weekly_rollup.subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "claude")):
        out = cluster_papers([
            {"arxiv_id": "2501.1", "title": "x", "tldr": "y", "tags": []},
            {"arxiv_id": "2501.2", "title": "z", "tldr": "w", "tags": []},
        ])
    assert len(out) == 1
    assert out[0]["arxiv_ids"] == ["2501.1", "2501.2"]
    assert "LLM clustering 失敗" in out[0]["summary"]


def test_cluster_papers_empty_input():
    assert cluster_papers([]) == []


def test_build_rollup_message_renders_clusters_and_links():
    papers = [
        {"arxiv_id": "2501.1", "title": "Paper A", "arxiv_url": "https://arxiv.org/abs/2501.1"},
        {"arxiv_id": "2501.2", "title": "Paper B", "arxiv_url": "https://arxiv.org/abs/2501.2"},
    ]
    clusters = [
        {"theme": "Diffusion", "summary": "one two three", "arxiv_ids": ["2501.1"]},
        {"theme": "RL", "summary": "four five", "arxiv_ids": ["2501.2"]},
    ]
    msg = build_rollup_message(clusters, papers, "2026-04-27")

    assert "Weekly Paper Rollup — 2026-04-27" in msg
    assert "(2 papers)" in msg
    assert "<b>1. Diffusion</b>" in msg
    assert "<b>2. RL</b>" in msg
    assert "Paper A" in msg
    assert "Paper B" in msg
    assert 'href="https://arxiv.org/abs/2501.1"' in msg


def test_build_rollup_skips_unknown_arxiv_ids():
    papers = [{"arxiv_id": "2501.1", "title": "A", "arxiv_url": "https://x"}]
    clusters = [{"theme": "t", "summary": "s", "arxiv_ids": ["2501.1", "missing"]}]
    msg = build_rollup_message(clusters, papers, "2026-04-27")
    assert "Paper A" not in msg  # sanity
    assert msg.count("<a href=") == 1  # only the known paper rendered as link
