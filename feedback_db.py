"""SQLite wrapper for Telegram feedback on paper pushes (like / dislike / save)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id   TEXT NOT NULL,
    action     TEXT NOT NULL,           -- "like" | "dislike" | "save"
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_arxiv  ON feedback(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_feedback_action ON feedback(action);
"""

VALID_ACTIONS = {"like", "dislike", "save"}


def init_feedback_db(db_path: Path | str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def record_feedback(
    db_path: Path | str, arxiv_id: str, action: str, user_id: str
) -> None:
    """Append a feedback row. Duplicates allowed (user may re-click)."""
    if action not in VALID_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO feedback (arxiv_id, action, user_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (arxiv_id, action, user_id, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_feedback(db_path: Path | str) -> list[dict]:
    """Return all feedback rows as {arxiv_id, action, user_id, created_at} dicts."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT arxiv_id, action, user_id, created_at "
            "FROM feedback ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"arxiv_id": r[0], "action": r[1], "user_id": r[2], "created_at": r[3]}
        for r in rows
    ]


def count_feedback(db_path: Path | str) -> int:
    """Total number of feedback rows (all actions)."""
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0])
    finally:
        conn.close()
