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
