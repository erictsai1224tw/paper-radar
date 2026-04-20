"""Tests for chat_db."""
from __future__ import annotations

from pathlib import Path

from chat_db import (
    append_turn,
    clear_history,
    get_history,
    init_chat_db,
)


def test_init_is_idempotent(tmp_db: Path):
    init_chat_db(tmp_db)
    init_chat_db(tmp_db)
    assert tmp_db.exists()


def test_append_and_get_history_returns_oldest_first(tmp_db: Path):
    init_chat_db(tmp_db)
    append_turn(tmp_db, "42", "user", "q1")
    append_turn(tmp_db, "42", "assistant", "a1")
    append_turn(tmp_db, "42", "user", "q2")
    rows = get_history(tmp_db, "42", limit=10)
    assert [r["role"] for r in rows] == ["user", "assistant", "user"]
    assert [r["text"] for r in rows] == ["q1", "a1", "q2"]


def test_get_history_limit_keeps_most_recent(tmp_db: Path):
    init_chat_db(tmp_db)
    for i in range(6):
        append_turn(tmp_db, "42", "user", f"m{i}")
    rows = get_history(tmp_db, "42", limit=3)
    assert [r["text"] for r in rows] == ["m3", "m4", "m5"]


def test_history_is_scoped_by_chat_id(tmp_db: Path):
    init_chat_db(tmp_db)
    append_turn(tmp_db, "42", "user", "hello")
    append_turn(tmp_db, "99", "user", "world")
    assert [r["text"] for r in get_history(tmp_db, "42", limit=10)] == ["hello"]
    assert [r["text"] for r in get_history(tmp_db, "99", limit=10)] == ["world"]


def test_clear_history_only_affects_given_chat(tmp_db: Path):
    init_chat_db(tmp_db)
    append_turn(tmp_db, "42", "user", "a")
    append_turn(tmp_db, "99", "user", "b")
    clear_history(tmp_db, "42")
    assert get_history(tmp_db, "42", limit=10) == []
    assert [r["text"] for r in get_history(tmp_db, "99", limit=10)] == ["b"]


from chat_db import get_offset, set_offset


def test_get_offset_returns_zero_when_unset(tmp_db: Path):
    init_chat_db(tmp_db)
    assert get_offset(tmp_db) == 0


def test_set_then_get_offset_roundtrip(tmp_db: Path):
    init_chat_db(tmp_db)
    set_offset(tmp_db, 12345)
    assert get_offset(tmp_db) == 12345


def test_set_offset_overwrites(tmp_db: Path):
    init_chat_db(tmp_db)
    set_offset(tmp_db, 1)
    set_offset(tmp_db, 99)
    assert get_offset(tmp_db) == 99
