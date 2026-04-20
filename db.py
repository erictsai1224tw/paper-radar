"""SQLite wrapper for dedup storage."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT,
    pushed_at TEXT
)
"""


def init_db(db_path: Path | str) -> None:
    """Create schema if missing. Idempotent."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_seen_ids(db_path: Path | str) -> set[str]:
    """Return every arxiv_id previously pushed."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT arxiv_id FROM seen").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def mark_seen(db_path: Path | str, papers: list[dict]) -> None:
    """Record papers as pushed. Upsert on arxiv_id."""
    now = datetime.now().isoformat(timespec="seconds")
    rows = [(p["arxiv_id"], p["title"], now) for p in papers]
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO seen (arxiv_id, title, pushed_at) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
