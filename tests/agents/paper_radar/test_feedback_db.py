"""Tests for feedback_db."""
from __future__ import annotations

from pathlib import Path

import pytest

from feedback_db import (
    count_feedback,
    get_all_feedback,
    init_feedback_db,
    record_feedback,
)


def test_init_is_idempotent(tmp_db: Path):
    init_feedback_db(tmp_db)
    init_feedback_db(tmp_db)
    assert tmp_db.exists()


def test_record_and_read(tmp_db: Path):
    init_feedback_db(tmp_db)
    record_feedback(tmp_db, "2501.1", "like", "42")
    record_feedback(tmp_db, "2501.2", "dislike", "42")
    record_feedback(tmp_db, "2501.1", "save", "42")
    rows = get_all_feedback(tmp_db)
    assert len(rows) == 3
    assert [r["action"] for r in rows] == ["like", "dislike", "save"]
    assert rows[0]["arxiv_id"] == "2501.1"
    assert rows[0]["user_id"] == "42"


def test_count_feedback(tmp_db: Path):
    init_feedback_db(tmp_db)
    assert count_feedback(tmp_db) == 0
    for action in ("like", "like", "dislike"):
        record_feedback(tmp_db, "2501.1", action, "42")
    assert count_feedback(tmp_db) == 3


def test_record_rejects_invalid_action(tmp_db: Path):
    init_feedback_db(tmp_db)
    with pytest.raises(ValueError):
        record_feedback(tmp_db, "2501.1", "wtf", "42")


def test_duplicate_clicks_allowed(tmp_db: Path):
    """User might re-click — we store every click (dedup is a query-time concern)."""
    init_feedback_db(tmp_db)
    record_feedback(tmp_db, "2501.1", "like", "42")
    record_feedback(tmp_db, "2501.1", "like", "42")
    assert count_feedback(tmp_db) == 2
