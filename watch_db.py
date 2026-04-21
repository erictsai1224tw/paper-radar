"""SQLite wrapper for saved arxiv search queries — powers /watch persistent topics."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    name       TEXT PRIMARY KEY,
    query      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_seen (
    watch_name TEXT NOT NULL,
    arxiv_id   TEXT NOT NULL,
    seen_at    TEXT NOT NULL,
    PRIMARY KEY (watch_name, arxiv_id)
);
CREATE INDEX IF NOT EXISTS idx_watch_seen_name ON watch_seen(watch_name);
"""


def init_watch_db(db_path: Path | str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def upsert_watch(db_path: Path | str, name: str, query: str) -> bool:
    """Insert or update a watch. Returns True if created, False if updated."""
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        existing = conn.execute(
            "SELECT 1 FROM watches WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE watches SET query = ?, updated_at = ? WHERE name = ?",
                (query, now, name),
            )
        else:
            conn.execute(
                "INSERT INTO watches (name, query, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (name, query, now, now),
            )
        conn.commit()
    finally:
        conn.close()
    return not existing


def remove_watch(db_path: Path | str, name: str) -> bool:
    """Delete a watch by name. Returns True if a row was removed."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("DELETE FROM watches WHERE name = ?", (name,))
        conn.execute("DELETE FROM watch_seen WHERE watch_name = ?", (name,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_watches(db_path: Path | str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name, query, created_at, updated_at FROM watches ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"name": r[0], "query": r[1], "created_at": r[2], "updated_at": r[3]}
        for r in rows
    ]


def get_watch(db_path: Path | str, name: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name, query, created_at, updated_at FROM watches WHERE name = ?",
            (name,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"name": row[0], "query": row[1], "created_at": row[2], "updated_at": row[3]}


def get_seen_for_watch(db_path: Path | str, name: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT arxiv_id FROM watch_seen WHERE watch_name = ?", (name,)
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def mark_seen_for_watch(db_path: Path | str, name: str, arxiv_ids: list[str]) -> None:
    if not arxiv_ids:
        return
    now = datetime.now().isoformat(timespec="seconds")
    rows = [(name, aid, now) for aid in arxiv_ids]
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO watch_seen (watch_name, arxiv_id, seen_at) "
            "VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
