"""Tests for prompts.build_chat_prompt."""
from __future__ import annotations

from prompts import BOT_SYSTEM_PROMPT, build_chat_prompt


def test_build_chat_prompt_without_history_includes_system_and_current():
    out = build_chat_prompt(history=[], current="hello")
    assert BOT_SYSTEM_PROMPT in out
    assert "目前提問" in out
    assert out.rstrip().endswith("user: hello")


def test_build_chat_prompt_renders_history_oldest_first():
    hist = [
        {"role": "user", "text": "q1"},
        {"role": "assistant", "text": "a1"},
        {"role": "user", "text": "q2"},
    ]
    out = build_chat_prompt(history=hist, current="q3")

    i_q1 = out.index("q1")
    i_a1 = out.index("a1")
    i_q2 = out.index("q2")
    i_q3 = out.index("q3")
    assert i_q1 < i_a1 < i_q2 < i_q3

    assert "user: q1" in out
    assert "assistant: a1" in out
    assert "user: q3" in out


def test_build_chat_prompt_omits_history_block_when_empty():
    out = build_chat_prompt(history=[], current="x")
    assert "對話歷史" not in out


def test_build_chat_prompt_includes_todays_papers_when_given():
    papers = [
        {"title": "Paper A", "year": 2025, "tldr": "A短摘要", "arxiv_url": "https://arxiv.org/abs/2501.00001", "tags": ["llm"]},
        {"title": "Paper B", "year": 2024, "tldr": "B短摘要", "arxiv_url": "https://arxiv.org/abs/2412.00002", "tags": []},
    ]
    out = build_chat_prompt(history=[], current="介紹第 1 篇", todays_papers=papers)
    assert "今日 paper_radar 推播的論文" in out
    assert '1. "Paper A"' in out
    assert "(2025)" in out
    assert "A短摘要" in out
    assert '2. "Paper B"' in out
    # first paper must appear before second and before the current question
    assert out.index("Paper A") < out.index("Paper B") < out.index("介紹第 1 篇")


def test_build_chat_prompt_omits_papers_block_when_empty_or_none():
    out_none = build_chat_prompt(history=[], current="x")
    out_empty = build_chat_prompt(history=[], current="x", todays_papers=[])
    for out in (out_none, out_empty):
        assert "paper_radar 推播" not in out


def test_build_chat_prompt_includes_paper_fulltext_when_given():
    out = build_chat_prompt(
        history=[],
        current="第 1 篇用什麼 dataset?",
        paper_fulltext="# Paper A\n\n## Datasets\nImageNet, COCO",
    )
    assert "論文全文" in out
    assert "ImageNet" in out
    assert out.index("ImageNet") < out.index("第 1 篇用什麼 dataset?")


def test_build_chat_prompt_omits_fulltext_when_empty_or_none():
    out_none = build_chat_prompt(history=[], current="x")
    out_empty = build_chat_prompt(history=[], current="x", paper_fulltext="")
    for out in (out_none, out_empty):
        assert "論文全文" not in out
