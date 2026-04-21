"""Tests for watch_db."""
from __future__ import annotations

from pathlib import Path

from watch_db import (
    get_seen_for_watch,
    get_watch,
    init_watch_db,
    list_watches,
    mark_seen_for_watch,
    remove_watch,
    upsert_watch,
)


def test_init_idempotent(tmp_db: Path):
    init_watch_db(tmp_db)
    init_watch_db(tmp_db)
    assert tmp_db.exists()


def test_upsert_creates_then_updates(tmp_db: Path):
    init_watch_db(tmp_db)
    assert upsert_watch(tmp_db, "rl", "abs:rl") is True
    assert upsert_watch(tmp_db, "rl", "abs:reinforcement") is False  # update
    assert get_watch(tmp_db, "rl")["query"] == "abs:reinforcement"


def test_list_orders_by_name(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "q1")
    upsert_watch(tmp_db, "diffusion", "q2")
    names = [w["name"] for w in list_watches(tmp_db)]
    assert names == ["diffusion", "rl"]


def test_remove_deletes_watch_and_its_seen(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "q")
    mark_seen_for_watch(tmp_db, "rl", ["2501.00001", "2501.00002"])
    assert remove_watch(tmp_db, "rl") is True
    assert get_watch(tmp_db, "rl") is None
    assert get_seen_for_watch(tmp_db, "rl") == set()


def test_remove_nonexistent_returns_false(tmp_db: Path):
    init_watch_db(tmp_db)
    assert remove_watch(tmp_db, "nope") is False


def test_mark_seen_dedups_repeated_calls(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "q")
    mark_seen_for_watch(tmp_db, "rl", ["a", "b"])
    mark_seen_for_watch(tmp_db, "rl", ["a", "c"])  # 'a' already seen
    assert get_seen_for_watch(tmp_db, "rl") == {"a", "b", "c"}


def test_seen_scoped_per_watch(tmp_db: Path):
    init_watch_db(tmp_db)
    upsert_watch(tmp_db, "rl", "q1")
    upsert_watch(tmp_db, "cv", "q2")
    mark_seen_for_watch(tmp_db, "rl", ["x"])
    mark_seen_for_watch(tmp_db, "cv", ["y"])
    assert get_seen_for_watch(tmp_db, "rl") == {"x"}
    assert get_seen_for_watch(tmp_db, "cv") == {"y"}
