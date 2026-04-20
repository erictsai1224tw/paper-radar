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


from dataclasses import dataclass, field
from pathlib import Path

from chat_db import append_turn, get_history, init_chat_db
from bot import Context, handle_update


@dataclass
class FakeContext:
    sent: list[tuple] = field(default_factory=list)
    actions: list[tuple] = field(default_factory=list)
    llm_calls: list[tuple] = field(default_factory=list)
    llm_reply: str = "llm-reply"
    llm_error: Exception | None = None


def _mk_ctx(tmp_db: Path, **overrides) -> Context:
    init_chat_db(tmp_db)
    fake = FakeContext()

    def send(chat_id, text):
        fake.sent.append((chat_id, text))

    def action(chat_id, a):
        fake.actions.append((chat_id, a))

    def ask(text, history, backend, timeout):
        fake.llm_calls.append((text, backend))
        if fake.llm_error is not None:
            raise fake.llm_error
        return fake.llm_reply

    ctx = Context(
        db_path=tmp_db,
        whitelist={"42"},
        default_backend=overrides.get("default_backend", "claude"),
        history_turns=overrides.get("history_turns", 10),
        llm_timeout=60,
        send_message=send,
        send_chat_action=action,
        ask_llm=ask,
    )
    ctx._fake = fake  # type: ignore[attr-defined]
    return ctx


def _msg(chat_id: str, text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": int(chat_id)}, "text": text}}


def test_unauthorized_chat_is_refused_without_llm(tmp_db: Path):
    ctx = _mk_ctx(tmp_db)
    handle_update(_msg("999", "hi"), ctx)
    assert ctx._fake.llm_calls == []
    assert len(ctx._fake.sent) == 1
    assert "unauthorized" in ctx._fake.sent[0][1].lower()


def test_start_command_replies_with_help_without_calling_llm(tmp_db: Path):
    ctx = _mk_ctx(tmp_db)
    handle_update(_msg("42", "/start"), ctx)
    assert ctx._fake.llm_calls == []
    assert len(ctx._fake.sent) == 1


def test_help_command_replies(tmp_db: Path):
    ctx = _mk_ctx(tmp_db)
    handle_update(_msg("42", "/help"), ctx)
    assert len(ctx._fake.sent) == 1


def test_reset_clears_history(tmp_db: Path):
    ctx = _mk_ctx(tmp_db)
    append_turn(tmp_db, "42", "user", "old")
    handle_update(_msg("42", "/reset"), ctx)
    assert get_history(tmp_db, "42", limit=10) == []
    assert ctx._fake.llm_calls == []


def test_backend_command_reports_default(tmp_db: Path):
    ctx = _mk_ctx(tmp_db, default_backend="gemini")
    handle_update(_msg("42", "/backend"), ctx)
    assert any("gemini" in t for _, t in ctx._fake.sent)


def test_plain_text_uses_default_backend_and_records_history(tmp_db: Path):
    ctx = _mk_ctx(tmp_db, default_backend="claude")
    ctx._fake.llm_reply = "hi there"
    handle_update(_msg("42", "hello"), ctx)
    assert ctx._fake.llm_calls == [("hello", "claude")]
    assert ctx._fake.actions == [("42", "typing")]
    hist = get_history(tmp_db, "42", limit=10)
    assert [h["role"] for h in hist] == ["user", "assistant"]
    assert [h["text"] for h in hist] == ["hello", "hi there"]


def test_slash_claude_forces_claude_regardless_of_default(tmp_db: Path):
    ctx = _mk_ctx(tmp_db, default_backend="gemini")
    handle_update(_msg("42", "/claude what is rag?"), ctx)
    assert ctx._fake.llm_calls == [("what is rag?", "claude")]
    hist = get_history(tmp_db, "42", limit=10)
    assert [h["text"] for h in hist] == ["what is rag?", "llm-reply"]


def test_slash_gemini_forces_gemini(tmp_db: Path):
    ctx = _mk_ctx(tmp_db, default_backend="claude")
    handle_update(_msg("42", "/gemini solve x"), ctx)
    assert ctx._fake.llm_calls == [("solve x", "gemini")]


def test_bare_slash_claude_returns_help(tmp_db: Path):
    ctx = _mk_ctx(tmp_db)
    handle_update(_msg("42", "/claude"), ctx)
    assert ctx._fake.llm_calls == []
    assert any("需要問題內容" in t for _, t in ctx._fake.sent)


def test_llm_error_replies_with_generic_message_and_skips_history(tmp_db: Path):
    import subprocess as sp
    ctx = _mk_ctx(tmp_db)
    ctx._fake.llm_error = sp.TimeoutExpired(cmd="claude", timeout=60)
    handle_update(_msg("42", "hi"), ctx)
    assert "失敗" in ctx._fake.sent[-1][1] or "超時" in ctx._fake.sent[-1][1]
    assert get_history(tmp_db, "42", limit=10) == []


def test_update_without_text_is_ignored(tmp_db: Path):
    ctx = _mk_ctx(tmp_db)
    handle_update({"update_id": 1, "message": {"chat": {"id": 42}}}, ctx)
    assert ctx._fake.sent == []
    assert ctx._fake.llm_calls == []
