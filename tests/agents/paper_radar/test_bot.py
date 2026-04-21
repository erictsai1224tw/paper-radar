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


def test_load_whitelist_does_not_fall_back_to_notify_chat_id(monkeypatch):
    """No silent fallback — Q&A bot has its own explicit allowlist."""
    monkeypatch.delenv("TELEGRAM_AUTHORIZED_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_NOTIFY_CHAT_ID", "77")
    assert load_whitelist() == set()


def test_load_whitelist_empty_when_nothing_set(monkeypatch):
    monkeypatch.delenv("TELEGRAM_AUTHORIZED_CHAT_IDS", raising=False)
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

    def ask(text, history, backend, timeout, **kwargs):
        fake.llm_calls.append((text, backend, kwargs))
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
        typing_interval=overrides.get("typing_interval", 4.0),
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
    assert [(c[0], c[1]) for c in ctx._fake.llm_calls] == [("hello", "claude")]
    assert ("42", "typing") in ctx._fake.actions
    hist = get_history(tmp_db, "42", limit=10)
    assert [h["role"] for h in hist] == ["user", "assistant"]
    assert [h["text"] for h in hist] == ["hello", "hi there"]


def test_typing_indicator_pumps_during_slow_llm(tmp_db: Path):
    """Pump should re-fire the typing indicator at least twice if LLM is slow."""
    import time as _time

    ctx = _mk_ctx(tmp_db, typing_interval=0.02)

    def slow_llm(text, history, backend, timeout, **kwargs):
        ctx._fake.llm_calls.append((text, backend, kwargs))
        _time.sleep(0.1)
        return "ok"

    ctx.ask_llm = slow_llm
    handle_update(_msg("42", "hi"), ctx)
    assert ctx._fake.actions.count(("42", "typing")) >= 2


def test_slash_claude_forces_claude_regardless_of_default(tmp_db: Path):
    ctx = _mk_ctx(tmp_db, default_backend="gemini")
    handle_update(_msg("42", "/claude what is rag?"), ctx)
    assert [(c[0], c[1]) for c in ctx._fake.llm_calls] == [("what is rag?", "claude")]
    hist = get_history(tmp_db, "42", limit=10)
    assert [h["text"] for h in hist] == ["what is rag?", "llm-reply"]


def test_slash_gemini_forces_gemini(tmp_db: Path):
    ctx = _mk_ctx(tmp_db, default_backend="claude")
    handle_update(_msg("42", "/gemini solve x"), ctx)
    assert [(c[0], c[1]) for c in ctx._fake.llm_calls] == [("solve x", "gemini")]


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


from bot import detect_paper_index, load_paper_fulltext


@pytest.mark.parametrize(
    "text,expected",
    [
        ("介紹第7篇", 7),
        ("第 7 篇論文在講什麼？", 7),
        ("第  12  篇", 12),
        ("第1篇", 1),
        ("介紹第一篇", 1),
        ("第七篇的 method 細節", 7),
        ("那第 十 篇呢", 10),
        ("what is rag?", None),
        ("", None),
    ],
)
def test_detect_paper_index(text, expected):
    assert detect_paper_index(text) == expected


def test_load_paper_fulltext_hit(tmp_path: Path):
    (tmp_path / "2501.00001.md").write_text("body", encoding="utf-8")
    papers = [{"arxiv_id": "2501.00001", "title": "A"}]
    assert load_paper_fulltext(1, papers, tmp_path) == "body"


def test_load_paper_fulltext_out_of_range(tmp_path: Path):
    papers = [{"arxiv_id": "2501.00001"}]
    assert load_paper_fulltext(0, papers, tmp_path) is None
    assert load_paper_fulltext(2, papers, tmp_path) is None


def test_load_paper_fulltext_missing_file(tmp_path: Path):
    papers = [{"arxiv_id": "2501.00999"}]
    assert load_paper_fulltext(1, papers, tmp_path) is None


def test_handle_update_attaches_paper_fulltext_when_index_detected(tmp_db: Path, tmp_path: Path):
    (tmp_path / "2501.12345.md").write_text("FULLTEXT HERE", encoding="utf-8")
    ctx = _mk_ctx(tmp_db)
    ctx.todays_papers = [{"arxiv_id": "2501.12345", "title": "P"}]
    ctx.papers_md_dir = tmp_path
    handle_update(_msg("42", "介紹第1篇的細節"), ctx)
    assert ctx._fake.llm_calls[0][2].get("paper_fulltext") == "FULLTEXT HERE"


def test_handle_update_no_fulltext_when_no_index_in_text(tmp_db: Path, tmp_path: Path):
    (tmp_path / "2501.12345.md").write_text("FT", encoding="utf-8")
    ctx = _mk_ctx(tmp_db)
    ctx.todays_papers = [{"arxiv_id": "2501.12345"}]
    ctx.papers_md_dir = tmp_path
    handle_update(_msg("42", "隨便問個普通問題"), ctx)
    assert ctx._fake.llm_calls[0][2].get("paper_fulltext") is None


from bot import (
    detect_arxiv_id,
    detect_paper_by_title,
    load_paper_markdown_by_id,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("介紹 2604.16044 這篇", "2604.16044"),
        ("介紹2604.16044", "2604.16044"),        # no space, Chinese neighbour
        ("2604.16044介紹一下", "2604.16044"),      # trailing Chinese
        ("arxiv.org/abs/2501.00001", "2501.00001"),
        ("2025.1234 and 2026.56789", "2025.1234"),  # first match wins
        ("no id here", None),
        ("12345.6789", None),  # wrong digit counts
        ("1234.56", None),     # suffix too short
    ],
)
def test_detect_arxiv_id(text, expected):
    assert detect_arxiv_id(text) == expected


def test_load_paper_markdown_by_id_hit(tmp_path: Path):
    (tmp_path / "2604.16044.md").write_text("paper body", encoding="utf-8")
    assert load_paper_markdown_by_id("2604.16044", tmp_path) == "paper body"


def test_load_paper_markdown_by_id_miss(tmp_path: Path):
    assert load_paper_markdown_by_id("2604.99999", tmp_path) is None


def test_load_paper_markdown_by_id_empty_arxiv_id(tmp_path: Path):
    assert load_paper_markdown_by_id("", tmp_path) is None


def test_detect_paper_by_title_matches_long_substring():
    papers = [
        {"arxiv_id": "x1", "title": "Elucidating the SNR-t Bias of Diffusion Probabilistic Models"},
        {"arxiv_id": "x2", "title": "Another Random Paper"},
    ]
    # a 15-char substring
    text = "想問 Elucidating the SNR 那篇講什麼"
    assert detect_paper_by_title(text, papers) == "x1"


def test_detect_paper_by_title_case_insensitive():
    papers = [{"arxiv_id": "x1", "title": "PersonaVLM: Long-Term Personalization"}]
    text = "personavlm: long-term per 講了什麼?"
    assert detect_paper_by_title(text, papers) == "x1"


def test_detect_paper_by_title_short_substring_does_not_match():
    papers = [{"arxiv_id": "x1", "title": "Very Short"}]
    # 'Short' alone = 5 chars, below the 12-char floor → no match
    assert detect_paper_by_title("the word short", papers) is None


def test_detect_paper_by_title_empty_input_or_papers():
    assert detect_paper_by_title("", []) is None
    assert detect_paper_by_title("any text", []) is None
    assert detect_paper_by_title("", [{"arxiv_id": "x", "title": "y"}]) is None


def test_handle_update_loads_fulltext_from_arxiv_id_even_if_not_in_todays(tmp_db: Path, tmp_path: Path):
    (tmp_path / "2604.16044.md").write_text("YESTERDAY FULLTEXT", encoding="utf-8")
    ctx = _mk_ctx(tmp_db)
    # today's batch doesn't include 2604.16044 — only recent_papers has it
    ctx.todays_papers = [{"arxiv_id": "2604.00000", "title": "new paper"}]
    ctx.recent_papers = [{"arxiv_id": "2604.16044", "title": "Old Paper Title Here"}]
    ctx.papers_md_dir = tmp_path
    handle_update(_msg("42", "介紹 2604.16044"), ctx)
    assert ctx._fake.llm_calls[0][2].get("paper_fulltext") == "YESTERDAY FULLTEXT"


def test_handle_update_loads_fulltext_from_title_substring(tmp_db: Path, tmp_path: Path):
    (tmp_path / "2604.16044.md").write_text("FULLTEXT BY TITLE", encoding="utf-8")
    ctx = _mk_ctx(tmp_db)
    ctx.todays_papers = []
    ctx.recent_papers = [
        {"arxiv_id": "2604.16044", "title": "Elucidating the SNR-t Bias of Diffusion Models"},
    ]
    ctx.papers_md_dir = tmp_path
    handle_update(_msg("42", "講一下 Elucidating the SNR-t 那篇"), ctx)
    assert ctx._fake.llm_calls[0][2].get("paper_fulltext") == "FULLTEXT BY TITLE"


def test_handle_update_fetches_markdown_on_demand_when_not_cached(tmp_db: Path, tmp_path: Path):
    """User names an arxiv_id we've never cached — bot fetches PDF + converts + loads."""
    ctx = _mk_ctx(tmp_db)
    ctx.todays_papers = []
    ctx.recent_papers = []
    ctx.papers_md_dir = tmp_path

    def fake_fetch(arxiv_id, out_dir):
        p = Path(out_dir) / f"{arxiv_id}.md"
        p.write_text("ON-DEMAND BODY", encoding="utf-8")
        return p

    with patch("paper_markdown.fetch_pdf_as_markdown", side_effect=fake_fetch):
        handle_update(_msg("42", "介紹 2401.12345"), ctx)

    assert ctx._fake.llm_calls[0][2].get("paper_fulltext") == "ON-DEMAND BODY"


def test_handle_update_on_demand_fetch_failure_degrades_gracefully(tmp_db: Path, tmp_path: Path):
    ctx = _mk_ctx(tmp_db)
    ctx.todays_papers = []
    ctx.recent_papers = []
    ctx.papers_md_dir = tmp_path

    with patch("paper_markdown.fetch_pdf_as_markdown", return_value=None):
        handle_update(_msg("42", "介紹 2401.12345"), ctx)

    # LLM still called, just without paper_fulltext
    assert ctx._fake.llm_calls[0][2].get("paper_fulltext") is None


from bot import run_loop


def test_run_loop_processes_updates_and_advances_offset(tmp_db: Path, monkeypatch):
    init_chat_db(tmp_db)
    monkeypatch.setenv("TELEGRAM_QA_BOT_TOKEN", "tok")

    seen: list[int] = []
    offsets: list[int] = []

    def fake_get_updates(token, offset, long_poll_timeout):
        offsets.append(offset)
        if offset == 0:
            return [
                {"update_id": 10, "message": {"chat": {"id": 42}, "text": "/help"}},
                {"update_id": 11, "message": {"chat": {"id": 42}, "text": "/reset"}},
            ]
        raise KeyboardInterrupt

    def fake_handler(upd, ctx):
        seen.append(upd["update_id"])

    try:
        run_loop(
            db_path=tmp_db,
            get_updates_fn=fake_get_updates,
            handler=fake_handler,
            ctx_factory=lambda: None,
            sleep_fn=lambda s: None,
        )
    except KeyboardInterrupt:
        pass

    assert seen == [10, 11]
    assert offsets[0] == 0
    assert offsets[1] == 12


def test_run_loop_advances_offset_even_when_handler_raises(tmp_db: Path, monkeypatch):
    init_chat_db(tmp_db)
    monkeypatch.setenv("TELEGRAM_QA_BOT_TOKEN", "tok")

    polls = [0]

    def fake_get_updates(token, offset, long_poll_timeout):
        polls[0] += 1
        if polls[0] == 1:
            return [{"update_id": 7, "message": {"chat": {"id": 42}, "text": "x"}}]
        raise KeyboardInterrupt

    def boom(upd, ctx):
        raise RuntimeError("handler broke")

    try:
        run_loop(
            db_path=tmp_db,
            get_updates_fn=fake_get_updates,
            handler=boom,
            ctx_factory=lambda: None,
            sleep_fn=lambda s: None,
        )
    except KeyboardInterrupt:
        pass

    from chat_db import get_offset
    assert get_offset(tmp_db) == 8


def test_run_loop_sleeps_on_get_updates_network_error(tmp_db: Path, monkeypatch):
    import requests as rq
    init_chat_db(tmp_db)
    monkeypatch.setenv("TELEGRAM_QA_BOT_TOKEN", "tok")

    slept: list[float] = []
    calls = [0]

    def fake_get_updates(token, offset, long_poll_timeout):
        calls[0] += 1
        if calls[0] == 1:
            raise rq.RequestException("boom")
        raise KeyboardInterrupt

    try:
        run_loop(
            db_path=tmp_db,
            get_updates_fn=fake_get_updates,
            handler=lambda u, c: None,
            ctx_factory=lambda: None,
            sleep_fn=lambda s: slept.append(s),
        )
    except KeyboardInterrupt:
        pass

    assert slept and slept[0] >= 1
