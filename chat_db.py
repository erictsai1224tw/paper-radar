"""SQLite wrapper for bot chat history + update-offset cursor."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_history_chat ON chat_history(chat_id, id);

CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_OFFSET_KEY = "update_offset"


def init_chat_db(db_path: Path | str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def append_turn(db_path: Path | str, chat_id: str, role: str, text: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO chat_history (chat_id, role, text, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, role, text, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_history(db_path: Path | str, chat_id: str, limit: int) -> list[dict]:
    """Return up to `limit` most recent rows for chat_id, oldest-first."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT role, text FROM chat_history "
            "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    finally:
        conn.close()
    rows.reverse()
    return [{"role": r[0], "text": r[1]} for r in rows]


def clear_history(db_path: Path | str, chat_id: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM chat_history WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()


def get_offset(db_path: Path | str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (_OFFSET_KEY,)
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


def set_offset(db_path: Path | str, offset: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
            (_OFFSET_KEY, str(offset)),
        )
        conn.commit()
    finally:
        conn.close()
