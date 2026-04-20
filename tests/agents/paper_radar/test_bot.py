"""Tests for bot.py."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from bot import ask_llm


def _fake_proc(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_ask_llm_claude_parses_result_field():
    stdout = json.dumps({"result": "hello from claude"})
    with patch("bot.subprocess.run", return_value=_fake_proc(stdout)) as mock_run:
        reply = ask_llm("q", history=[], backend="claude", timeout=60)
    assert reply == "hello from claude"
    argv = mock_run.call_args.args[0]
    assert argv[0] == "claude"
    assert "--max-turns" in argv and argv[argv.index("--max-turns") + 1] == "1"


def test_ask_llm_gemini_parses_response_field():
    stdout = json.dumps({"response": "hello from gemini"})
    with patch("bot.subprocess.run", return_value=_fake_proc(stdout)):
        reply = ask_llm("q", history=[], backend="gemini", timeout=60)
    assert reply == "hello from gemini"


def test_ask_llm_strips_json_fence_from_claude_output():
    stdout = json.dumps({"result": "plain text reply"})
    with patch("bot.subprocess.run", return_value=_fake_proc(stdout)):
        assert ask_llm("q", history=[], backend="claude", timeout=60) == "plain text reply"


def test_ask_llm_raises_on_unknown_backend():
    with pytest.raises(ValueError):
        ask_llm("q", history=[], backend="mystery", timeout=60)


def test_ask_llm_propagates_timeout():
    with patch(
        "bot.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=60),
    ):
        with pytest.raises(subprocess.TimeoutExpired):
            ask_llm("q", history=[], backend="claude", timeout=60)


from bot import is_authorized, load_whitelist


def test_load_whitelist_reads_csv(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_CHAT_IDS", "1,22, 333 ")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert load_whitelist() == {"1", "22", "333"}


def test_load_whitelist_falls_back_to_telegram_chat_id(monkeypatch):
    monkeypatch.delenv("TELEGRAM_AUTHORIZED_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "77")
    assert load_whitelist() == {"77"}


def test_load_whitelist_authorized_overrides_chat_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_CHAT_IDS", "1,2")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    assert load_whitelist() == {"1", "2"}


def test_load_whitelist_empty_when_nothing_set(monkeypatch):
    monkeypatch.delenv("TELEGRAM_AUTHORIZED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert load_whitelist() == set()


def test_is_authorized_checks_membership():
    assert is_authorized("42", {"42", "99"}) is True
    assert is_authorized("100", {"42", "99"}) is False


from bot import split_for_telegram

TG_LIMIT = 4096


def test_split_returns_single_chunk_when_under_limit():
    assert split_for_telegram("hello") == ["hello"]


def test_split_returns_single_chunk_at_exactly_limit():
    s = "a" * TG_LIMIT
    assert split_for_telegram(s) == [s]


def test_split_prefers_double_newline_boundary():
    a = "a" * 4000
    b = "b" * 500
    s = f"{a}\n\n{b}"
    chunks = split_for_telegram(s)
    assert len(chunks) == 2
    assert chunks[0] == a
    assert chunks[1] == b


def test_split_falls_back_to_single_newline():
    a = "a" * 4000
    b = "b" * 500
    s = f"{a}\n{b}"
    chunks = split_for_telegram(s)
    assert len(chunks) == 2
    assert chunks[0] == a
    assert chunks[1] == b


def test_split_hard_splits_at_4096_when_no_boundary():
    s = "x" * 5000
    chunks = split_for_telegram(s)
    assert chunks[0] == "x" * 4096
    assert chunks[1] == "x" * (5000 - 4096)


def test_split_handles_very_long_input():
    s = "z" * 10000
    chunks = split_for_telegram(s)
    assert "".join(chunks) == s
    assert all(len(c) <= 4096 for c in chunks)
