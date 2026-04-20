"""Shared fixtures for paper_radar tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Fresh SQLite file per test. Caller runs init_*_db on it."""
    return tmp_path / "test.sqlite"
