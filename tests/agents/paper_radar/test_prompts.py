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
