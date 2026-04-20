# Telegram Q&A Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a long-polling Telegram bot to `paper_radar` that lets the user Q&A with `claude -p` / `gemini -p` through Telegram, reusing the existing bot token.

**Architecture:** New `bot.py` process running a `getUpdates` long-poll loop. Shared `telegram_client.py` replaces the inline HTTP calls in `radar.py`. `chat_db.py` backs conversation history and the update-offset cursor in a separate SQLite file. Deployed as a second `docker-compose` service; cron-driven `radar.py` keeps its current lifecycle.

**Tech Stack:** Python 3.12, `requests`, `python-dotenv`, `sqlite3` (stdlib), `subprocess` (shell out to `claude -p` / `gemini -p`), pytest + `monkeypatch` / `unittest.mock`.

**Spec:** `/app/docs/superpowers/specs/2026-04-20-telegram-qa-bot-design.md`

---

## File Structure

```
/app/
├── bot.py                              # NEW — long-poll loop + handlers
├── telegram_client.py                  # NEW — HTTP wrapper (shared)
├── chat_db.py                          # NEW — history + update offset
├── prompts.py                          # MODIFY — add BOT_SYSTEM_PROMPT + build_chat_prompt
├── radar.py                            # MODIFY — use telegram_client
├── .env.example                        # MODIFY — new env vars
├── docker-compose.yml                  # MODIFY — add paper_radar_bot service
├── verify/verify_bot.py                # NEW — manual smoke
└── tests/
    ├── __init__.py                     # NEW
    └── agents/
        ├── __init__.py                 # NEW
        └── paper_radar/
            ├── __init__.py             # NEW
            ├── conftest.py             # NEW — tmp_path sqlite fixtures
            ├── test_telegram_client.py # NEW
            ├── test_chat_db.py         # NEW
            ├── test_prompts.py         # NEW
            └── test_bot.py             # NEW
```

Each new module has one clear responsibility: `telegram_client` = HTTP, `chat_db` = persistence, `prompts` = text templates, `bot` = control flow. `bot.py` receives its dependencies via function parameters (not global imports inside handlers) so tests can inject fakes.

---

## Task 1: Scaffold tests dir + install pytest

**Files:**
- Create: `tests/__init__.py`, `tests/agents/__init__.py`, `tests/agents/paper_radar/__init__.py`
- Create: `tests/agents/paper_radar/conftest.py`

- [ ] **Step 1: Verify pytest is installed**

Run: `pytest --version`
Expected: prints version ≥ 7.0. If missing: `uv pip install pytest` (dev group already lists it).

- [ ] **Step 2: Create empty `__init__.py` files**

Create three empty files:
- `tests/__init__.py`
- `tests/agents/__init__.py`
- `tests/agents/paper_radar/__init__.py`

- [ ] **Step 3: Create `tests/agents/paper_radar/conftest.py`**

```python
"""Shared fixtures for paper_radar tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Fresh SQLite file per test. Caller runs init_*_db on it."""
    return tmp_path / "test.sqlite"
```

- [ ] **Step 4: Verify pytest collects nothing yet but runs cleanly**

Run: `cd /app && pytest tests/ -v`
Expected: `no tests ran` (exit 5 is OK) — confirms test discovery works.

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/agents/__init__.py tests/agents/paper_radar/__init__.py tests/agents/paper_radar/conftest.py
git commit -m "test: scaffold tests/agents/paper_radar/ with conftest"
```

---

## Task 2: `telegram_client.py` — send_message

**Files:**
- Create: `telegram_client.py`
- Create: `tests/agents/paper_radar/test_telegram_client.py`

- [ ] **Step 1: Write failing test for `send_message`**

Create `tests/agents/paper_radar/test_telegram_client.py`:

```python
"""Tests for telegram_client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from telegram_client import send_message


def _mock_resp(status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    return resp


def test_send_message_posts_to_correct_url_with_payload():
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_message("tok123", "42", "hi")

    assert mock_post.call_count == 1
    url = mock_post.call_args.args[0]
    kwargs = mock_post.call_args.kwargs
    assert url == "https://api.telegram.org/bottok123/sendMessage"
    assert kwargs["json"] == {
        "chat_id": "42",
        "text": "hi",
        "disable_web_page_preview": True,
    }
    assert kwargs["timeout"] == 30


def test_send_message_includes_parse_mode_when_given():
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_message("tok", "1", "x", parse_mode="HTML")

    assert mock_post.call_args.kwargs["json"]["parse_mode"] == "HTML"


def test_send_message_raises_on_http_error():
    resp = _mock_resp()
    resp.raise_for_status.side_effect = requests.HTTPError("400")
    with patch("telegram_client.requests.post", return_value=resp):
        with pytest.raises(requests.HTTPError):
            send_message("tok", "1", "x")
```

- [ ] **Step 2: Run test — verify it fails with ImportError**

Run: `cd /app && pytest tests/agents/paper_radar/test_telegram_client.py -v`
Expected: `ModuleNotFoundError: No module named 'telegram_client'`

- [ ] **Step 3: Create `telegram_client.py` with `send_message`**

```python
"""Thin wrapper around Telegram Bot API. Pure functions, no global state."""
from __future__ import annotations

import requests

_API = "https://api.telegram.org/bot{token}/{method}"
_DEFAULT_TIMEOUT = 30


def send_message(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    disable_preview: bool = True,
) -> None:
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = requests.post(
        _API.format(token=token, method="sendMessage"),
        json=payload,
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
```

- [ ] **Step 4: Run test — verify it passes**

Run: `cd /app && pytest tests/agents/paper_radar/test_telegram_client.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add telegram_client.py tests/agents/paper_radar/test_telegram_client.py
git commit -m "feat: add telegram_client.send_message"
```

---

## Task 3: `telegram_client.py` — send_chat_action + get_updates

**Files:**
- Modify: `telegram_client.py`
- Modify: `tests/agents/paper_radar/test_telegram_client.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/agents/paper_radar/test_telegram_client.py`:

```python
from telegram_client import get_updates, send_chat_action


def test_send_chat_action_posts_typing():
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_chat_action("tok", "42", "typing")

    assert mock_post.call_args.args[0] == "https://api.telegram.org/bottok/sendChatAction"
    assert mock_post.call_args.kwargs["json"] == {"chat_id": "42", "action": "typing"}


def test_get_updates_uses_long_poll_timeout_and_offset():
    with patch("telegram_client.requests.get") as mock_get:
        resp = _mock_resp()
        resp.json = MagicMock(return_value={"ok": True, "result": [{"update_id": 5}]})
        mock_get.return_value = resp
        out = get_updates("tok", offset=3, long_poll_timeout=25)

    assert out == [{"update_id": 5}]
    url = mock_get.call_args.args[0]
    params = mock_get.call_args.kwargs["params"]
    assert url == "https://api.telegram.org/bottok/getUpdates"
    assert params == {"offset": 3, "timeout": 25}
    # HTTP timeout must exceed long_poll_timeout so we don't cut off mid-poll
    assert mock_get.call_args.kwargs["timeout"] > 25


def test_get_updates_returns_empty_list_when_no_results():
    with patch("telegram_client.requests.get") as mock_get:
        resp = _mock_resp()
        resp.json = MagicMock(return_value={"ok": True, "result": []})
        mock_get.return_value = resp
        assert get_updates("tok", offset=0) == []
```

- [ ] **Step 2: Run — verify new tests fail**

Run: `cd /app && pytest tests/agents/paper_radar/test_telegram_client.py -v`
Expected: 3 new tests fail with `ImportError: cannot import name 'get_updates'`.

- [ ] **Step 3: Add `send_chat_action` + `get_updates`**

Append to `telegram_client.py`:

```python
def send_chat_action(token: str, chat_id: str, action: str) -> None:
    resp = requests.post(
        _API.format(token=token, method="sendChatAction"),
        json={"chat_id": chat_id, "action": action},
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()


def get_updates(
    token: str,
    offset: int,
    long_poll_timeout: int = 30,
) -> list[dict]:
    resp = requests.get(
        _API.format(token=token, method="getUpdates"),
        params={"offset": offset, "timeout": long_poll_timeout},
        timeout=long_poll_timeout + 10,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])
```

- [ ] **Step 4: Run — verify all 6 pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_telegram_client.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add telegram_client.py tests/agents/paper_radar/test_telegram_client.py
git commit -m "feat: add send_chat_action and get_updates to telegram_client"
```

---

## Task 4: Refactor `radar.py` to use `telegram_client.send_message`

**Files:**
- Modify: `radar.py` (remove `_send_telegram_message`, import `send_message`)

- [ ] **Step 1: Edit `radar.py`**

Replace the `_send_telegram_message` function and its two call sites. In `radar.py`:

Delete lines for `_send_telegram_message` (the `def _send_telegram_message(url, chat_id, text) -> None:` block).

Replace the `TELEGRAM_API = ...` constant — it can stay unused or be removed; remove it to reduce dead code:

```python
# delete this line:
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
```

Add import near the top (after `from prompts import ...`):

```python
from telegram_client import send_message as _tg_send
```

Rewrite `notify_telegram` body to use `_tg_send(bot_token, chat_id, text, parse_mode="HTML")`. The full new function:

```python
def notify_telegram(
    papers: list[dict],
    notion_url: str,
    bot_token: str,
    chat_id: str,
    today: str | None = None,
) -> None:
    """每篇 paper 各發一則 Telegram 訊息，最後附 Notion 連結。

    失敗時 log warning 但不 raise（Notion 已寫好）。
    """
    import html

    if today is None:
        today = date.today().isoformat()

    n = len(papers)

    try:
        _tg_send(
            bot_token, chat_id,
            f"📚 <b>AI Radar {html.escape(today)}</b> — {n} 篇新論文",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("notify_telegram header failed: %s", exc)
        return

    for i, paper in enumerate(papers, start=1):
        time.sleep(_TELEGRAM_MSG_DELAY)
        try:
            _tg_send(bot_token, chat_id, _build_paper_message(i, paper), parse_mode="HTML")
        except Exception as exc:
            logger.warning("notify_telegram paper %s failed: %s", paper.get("arxiv_id"), exc)

    time.sleep(_TELEGRAM_MSG_DELAY)
    try:
        _tg_send(
            bot_token, chat_id,
            f'<a href="{html.escape(notion_url, quote=True)}">👉 看 Notion 完整整理</a>',
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("notify_telegram notion link failed: %s", exc)
```

- [ ] **Step 2: Verify `radar.py` still parses**

Run: `cd /app && python -c "import radar; print(radar.notify_telegram.__doc__)"`
Expected: the docstring prints with no import errors.

- [ ] **Step 3: Run existing telegram client tests to confirm no regression**

Run: `cd /app && pytest tests/agents/paper_radar/test_telegram_client.py -v`
Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add radar.py
git commit -m "refactor: route radar.notify_telegram through telegram_client"
```

---

## Task 5: `chat_db.py` — init_chat_db + append/get/clear history

**Files:**
- Create: `chat_db.py`
- Create: `tests/agents/paper_radar/test_chat_db.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/paper_radar/test_chat_db.py`:

```python
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
```

- [ ] **Step 2: Run — verify failure**

Run: `cd /app && pytest tests/agents/paper_radar/test_chat_db.py -v`
Expected: `ModuleNotFoundError: No module named 'chat_db'`

- [ ] **Step 3: Create `chat_db.py`**

```python
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
```

- [ ] **Step 4: Run — verify all 5 history tests pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_chat_db.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add chat_db.py tests/agents/paper_radar/test_chat_db.py
git commit -m "feat: add chat_db with history persistence"
```

---

## Task 6: `chat_db.py` — update offset cursor

**Files:**
- Modify: `chat_db.py`
- Modify: `tests/agents/paper_radar/test_chat_db.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/agents/paper_radar/test_chat_db.py`:

```python
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
```

- [ ] **Step 2: Run — verify 3 new failures**

Run: `cd /app && pytest tests/agents/paper_radar/test_chat_db.py -v`
Expected: 3 fail with `ImportError: cannot import name 'get_offset'`.

- [ ] **Step 3: Add offset functions**

Append to `chat_db.py`:

```python
_OFFSET_KEY = "update_offset"


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
```

- [ ] **Step 4: Run — verify all 8 pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_chat_db.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add chat_db.py tests/agents/paper_radar/test_chat_db.py
git commit -m "feat: add update-offset persistence to chat_db"
```

---

## Task 7: `prompts.py` — BOT_SYSTEM_PROMPT + build_chat_prompt

**Files:**
- Modify: `prompts.py`
- Create: `tests/agents/paper_radar/test_prompts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/paper_radar/test_prompts.py`:

```python
"""Tests for prompts.build_chat_prompt."""
from __future__ import annotations

from prompts import BOT_SYSTEM_PROMPT, build_chat_prompt


def test_build_chat_prompt_without_history_includes_system_and_current():
    out = build_chat_prompt(history=[], current="hello")
    assert BOT_SYSTEM_PROMPT in out
    assert "目前提問" in out
    assert out.rstrip().endswith("user: hello")


def test_build_chat_prompt_renders_history_oldest_first():
    hist = [
        {"role": "user", "text": "q1"},
        {"role": "assistant", "text": "a1"},
        {"role": "user", "text": "q2"},
    ]
    out = build_chat_prompt(history=hist, current="q3")

    # history section present, in order
    i_q1 = out.index("q1")
    i_a1 = out.index("a1")
    i_q2 = out.index("q2")
    i_q3 = out.index("q3")
    assert i_q1 < i_a1 < i_q2 < i_q3

    # roles prefixed
    assert "user: q1" in out
    assert "assistant: a1" in out
    assert "user: q3" in out


def test_build_chat_prompt_omits_history_block_when_empty():
    out = build_chat_prompt(history=[], current="x")
    assert "對話歷史" not in out
```

- [ ] **Step 2: Run — verify failure**

Run: `cd /app && pytest tests/agents/paper_radar/test_prompts.py -v`
Expected: `ImportError: cannot import name 'BOT_SYSTEM_PROMPT'`.

- [ ] **Step 3: Append to `prompts.py`**

Add at the bottom of `prompts.py`:

```python
BOT_SYSTEM_PROMPT = """你是使用者的 coding 助手，透過 Telegram 對話。
- 預設用繁體中文回答，除非問題本身是英文
- 程式碼用 ``` fence 包起來
- Telegram 訊息上限 4096 字元，回覆盡量精簡
- 不要編造 API、函式名、或檔案路徑
"""


def build_chat_prompt(history: list[dict], current: str) -> str:
    """Assemble system prompt + optional history block + current question."""
    parts = [BOT_SYSTEM_PROMPT]
    if history:
        parts.append("--- 對話歷史 ---")
        for h in history:
            parts.append(f"{h['role']}: {h['text']}")
    parts.append("--- 目前提問 ---")
    parts.append(f"user: {current}")
    return "\n".join(parts)
```

- [ ] **Step 4: Run — verify all 3 pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_prompts.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/agents/paper_radar/test_prompts.py
git commit -m "feat: add BOT_SYSTEM_PROMPT and build_chat_prompt"
```

---

## Task 8: `bot.py` — LLM invocation (`ask_llm`)

**Files:**
- Create: `bot.py`
- Create: `tests/agents/paper_radar/test_bot.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/paper_radar/test_bot.py`:

```python
"""Tests for bot.ask_llm."""
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
    # Bot replies are free-form text, NOT JSON — but the outer envelope might
    # still wrap text in a fence if the LLM chooses to. Should pass through unchanged
    # here (we do NOT inner-JSON-parse). This test pins that behavior.
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
```

- [ ] **Step 2: Run — verify failure**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: `ModuleNotFoundError: No module named 'bot'`.

- [ ] **Step 3: Create minimal `bot.py` with `ask_llm` only**

```python
"""Telegram Q&A bot — long-polling process.

See docs/superpowers/specs/2026-04-20-telegram-qa-bot-design.md for design.
"""
from __future__ import annotations

import json
import logging
import subprocess

from prompts import build_chat_prompt

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "sonnet"
_GEMINI_MODEL = "gemini-3-flash-preview"


def _run_claude_bot(prompt: str, timeout: int) -> str:
    argv = [
        "claude",
        "-p", prompt,
        "--model", _CLAUDE_MODEL,
        "--output-format", "json",
        "--max-turns", "1",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True,
        timeout=timeout, check=True,
    )
    return json.loads(proc.stdout)["result"]


def _run_gemini_bot(prompt: str, timeout: int) -> str:
    argv = [
        "gemini",
        "-p", prompt,
        "--model", _GEMINI_MODEL,
        "--output-format", "json",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True,
        timeout=timeout, check=True,
    )
    return json.loads(proc.stdout)["response"]


_BACKENDS = {"claude": _run_claude_bot, "gemini": _run_gemini_bot}


def ask_llm(text: str, history: list[dict], backend: str, timeout: int) -> str:
    """Shell out to `claude -p` / `gemini -p` with history-aware prompt."""
    runner = _BACKENDS.get(backend)
    if runner is None:
        raise ValueError(f"unknown backend {backend!r}")
    prompt = build_chat_prompt(history=history, current=text)
    return runner(prompt, timeout)
```

- [ ] **Step 4: Run — verify 5 pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/agents/paper_radar/test_bot.py
git commit -m "feat: add bot.ask_llm with claude/gemini backends"
```

---

## Task 9: `bot.py` — authorization

**Files:**
- Modify: `bot.py`
- Modify: `tests/agents/paper_radar/test_bot.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/agents/paper_radar/test_bot.py`:

```python
from bot import load_whitelist, is_authorized


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
```

- [ ] **Step 2: Run — verify failure**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 5 new tests fail with `ImportError: cannot import name 'load_whitelist'`.

- [ ] **Step 3: Add authorization helpers to `bot.py`**

Append to `bot.py`:

```python
import os


def load_whitelist() -> set[str]:
    raw = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "").strip()
    if raw:
        return {x.strip() for x in raw.split(",") if x.strip()}
    fallback = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return {fallback} if fallback else set()


def is_authorized(chat_id: str, whitelist: set[str]) -> bool:
    return chat_id in whitelist
```

(Move the `import os` to the top module imports if it makes the file cleaner.)

- [ ] **Step 4: Run — verify all 10 bot tests pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/agents/paper_radar/test_bot.py
git commit -m "feat: add whitelist auth to bot"
```

---

## Task 10: `bot.py` — reply chunking

**Files:**
- Modify: `bot.py`
- Modify: `tests/agents/paper_radar/test_bot.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/agents/paper_radar/test_bot.py`:

```python
from bot import split_for_telegram

TG_LIMIT = 4096


def test_split_returns_single_chunk_when_under_limit():
    assert split_for_telegram("hello") == ["hello"]


def test_split_returns_single_chunk_at_exactly_limit():
    s = "a" * TG_LIMIT
    assert split_for_telegram(s) == [s]


def test_split_prefers_double_newline_boundary():
    # first chunk must end BEFORE the \n\n
    a = "a" * 4000
    b = "b" * 500
    s = f"{a}\n\n{b}"
    chunks = split_for_telegram(s)
    assert len(chunks) == 2
    assert chunks[0] == a
    assert chunks[1] == b


def test_split_falls_back_to_single_newline():
    # no \n\n in the first 4096, but a \n exists
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
```

- [ ] **Step 2: Run — verify failure**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 6 new fail with `ImportError: cannot import name 'split_for_telegram'`.

- [ ] **Step 3: Add `split_for_telegram` to `bot.py`**

Append to `bot.py`:

```python
_TG_LIMIT = 4096


def split_for_telegram(text: str) -> list[str]:
    """Split `text` into Telegram-safe chunks (≤4096 chars each).

    Prefers splitting at the last \\n\\n before the limit, then the last \\n,
    then hard-splits at exactly 4096.
    """
    chunks: list[str] = []
    remaining = text
    while len(remaining) > _TG_LIMIT:
        window = remaining[:_TG_LIMIT]
        cut = window.rfind("\n\n")
        if cut == -1:
            cut = window.rfind("\n")
        if cut == -1:
            cut = _TG_LIMIT
            chunks.append(remaining[:cut])
            remaining = remaining[cut:]
            continue
        chunks.append(remaining[:cut])
        # skip the newline(s) that formed the boundary
        boundary_len = 2 if remaining[cut:cut + 2] == "\n\n" else 1
        remaining = remaining[cut + boundary_len:]
    if remaining:
        chunks.append(remaining)
    return chunks
```

- [ ] **Step 4: Run — verify all 16 bot tests pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/agents/paper_radar/test_bot.py
git commit -m "feat: add telegram-safe reply chunking"
```

---

## Task 11: `bot.py` — `handle_update` dispatch

**Files:**
- Modify: `bot.py`
- Modify: `tests/agents/paper_radar/test_bot.py`

The `handle_update` function takes a `Context` dataclass so tests can inject fakes for `send_message`, `send_chat_action`, `ask_llm`, and the db path. This keeps the dispatcher pure and testable.

- [ ] **Step 1: Append failing tests**

Append to `tests/agents/paper_radar/test_bot.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path

from chat_db import append_turn, get_history, init_chat_db
from bot import Context, handle_update


@dataclass
class FakeContext:
    sent: list[tuple] = field(default_factory=list)     # (chat_id, text)
    actions: list[tuple] = field(default_factory=list)  # (chat_id, action)
    llm_calls: list[tuple] = field(default_factory=list)  # (text, backend)
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
    # stash fake on ctx for test inspection
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
    assert [h["text"] for h in hist] == ["what is rag?", "llm-reply"]  # prefix stripped


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
```

- [ ] **Step 2: Run — verify failure**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 11 new tests fail with `ImportError: cannot import name 'Context'`.

- [ ] **Step 3: Add `Context` + `handle_update` to `bot.py`**

Append to `bot.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from chat_db import append_turn, clear_history, get_history


@dataclass
class Context:
    db_path: Path
    whitelist: set[str]
    default_backend: str
    history_turns: int
    llm_timeout: int
    send_message: Callable[[str, str], None]
    send_chat_action: Callable[[str, str], None]
    ask_llm: Callable[[str, list[dict], str, int], str]


_HELP_TEXT = (
    "可用指令：\n"
    "/help — 顯示這段\n"
    "/reset — 清空對話歷史\n"
    "/backend — 顯示目前預設 backend\n"
    "/claude <q> — 這則強制用 claude\n"
    "/gemini <q> — 這則強制用 gemini\n"
    "直接傳訊息：用預設 backend 回答，帶歷史"
)


def handle_update(upd: dict, ctx: Context) -> None:
    msg = upd.get("message") or {}
    text = msg.get("text")
    chat_id_raw = (msg.get("chat") or {}).get("id")
    if not text or chat_id_raw is None:
        return
    chat_id = str(chat_id_raw)

    if not is_authorized(chat_id, ctx.whitelist):
        logger.warning("unauthorized chat_id=%s", chat_id)
        ctx.send_message(chat_id, "unauthorized")
        return

    if text.startswith("/"):
        _handle_command(chat_id, text, ctx)
        return

    _handle_free_form(chat_id, text, ctx.default_backend, ctx)


def _handle_command(chat_id: str, text: str, ctx: Context) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        ctx.send_message(chat_id, _HELP_TEXT)
        return
    if cmd == "/reset":
        clear_history(ctx.db_path, chat_id)
        ctx.send_message(chat_id, "歷史已清空")
        return
    if cmd == "/backend":
        ctx.send_message(chat_id, f"目前 backend: {ctx.default_backend}")
        return
    if cmd in ("/claude", "/gemini"):
        if not arg.strip():
            ctx.send_message(chat_id, "需要問題內容")
            return
        backend = cmd[1:]  # strip leading "/"
        _handle_free_form(chat_id, arg, backend, ctx)
        return

    ctx.send_message(chat_id, f"未知指令：{cmd}\n{_HELP_TEXT}")


def _handle_free_form(chat_id: str, text: str, backend: str, ctx: Context) -> None:
    try:
        ctx.send_chat_action(chat_id, "typing")
    except Exception as exc:
        logger.warning("send_chat_action failed: %s", exc)

    history = get_history(ctx.db_path, chat_id, limit=ctx.history_turns * 2)
    try:
        reply = ctx.ask_llm(text, history, backend, ctx.llm_timeout)
    except Exception as exc:
        logger.warning("ask_llm failed for chat=%s: %s", chat_id, exc)
        ctx.send_message(chat_id, "⏱️ 回覆失敗，請再試一次")
        return

    append_turn(ctx.db_path, chat_id, "user", text)
    append_turn(ctx.db_path, chat_id, "assistant", reply)

    for chunk in split_for_telegram(reply):
        try:
            ctx.send_message(chat_id, chunk)
        except Exception as exc:
            logger.warning("send_message failed for chat=%s: %s", chat_id, exc)
            return
```

- [ ] **Step 4: Run — verify all 27 bot tests pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 27 passed.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/agents/paper_radar/test_bot.py
git commit -m "feat: add handle_update dispatcher with command support"
```

---

## Task 12: `bot.py` — main loop

**Files:**
- Modify: `bot.py`
- Modify: `tests/agents/paper_radar/test_bot.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/agents/paper_radar/test_bot.py`:

```python
from bot import run_loop


def test_run_loop_processes_updates_and_advances_offset(tmp_db: Path, monkeypatch):
    init_chat_db(tmp_db)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    seen: list[int] = []
    offsets: list[int] = []

    def fake_get_updates(token, offset, long_poll_timeout):
        offsets.append(offset)
        if offset == 0:
            return [
                {"update_id": 10, "message": {"chat": {"id": 42}, "text": "/help"}},
                {"update_id": 11, "message": {"chat": {"id": 42}, "text": "/reset"}},
            ]
        raise KeyboardInterrupt  # stop the loop after second poll

    def fake_handler(upd, ctx):
        seen.append(upd["update_id"])

    try:
        run_loop(
            db_path=tmp_db,
            get_updates_fn=fake_get_updates,
            handler=fake_handler,
            ctx_factory=lambda: None,  # handler doesn't use ctx here
            sleep_fn=lambda s: None,
        )
    except KeyboardInterrupt:
        pass

    assert seen == [10, 11]
    # first poll starts at 0, second uses 12 (last update_id + 1)
    assert offsets[0] == 0
    assert offsets[1] == 12


def test_run_loop_advances_offset_even_when_handler_raises(tmp_db: Path, monkeypatch):
    init_chat_db(tmp_db)

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
    assert get_offset(tmp_db) == 8  # advanced despite handler crash


def test_run_loop_sleeps_on_get_updates_network_error(tmp_db: Path, monkeypatch):
    import requests as rq
    init_chat_db(tmp_db)

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
```

- [ ] **Step 2: Run — verify failure**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 3 new tests fail with `ImportError: cannot import name 'run_loop'`.

- [ ] **Step 3: Add `run_loop` to `bot.py`**

Append to `bot.py`:

```python
import time
from typing import Callable

import requests

from chat_db import get_offset, set_offset, init_chat_db


def run_loop(
    db_path: Path,
    get_updates_fn: Callable[[str, int, int], list[dict]],
    handler: Callable[[dict, Context], None],
    ctx_factory: Callable[[], Context],
    sleep_fn: Callable[[float], None] = time.sleep,
    long_poll_timeout: int = 30,
) -> None:
    """Long-poll loop. Injects getUpdates + handler so tests can fake them."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    offset = get_offset(db_path)

    while True:
        try:
            updates = get_updates_fn(token, offset, long_poll_timeout)
        except requests.RequestException as exc:
            logger.warning("getUpdates failed: %s — sleeping 5s", exc)
            sleep_fn(5)
            continue

        ctx = ctx_factory()
        for upd in updates:
            try:
                handler(upd, ctx)
            except Exception:
                logger.exception("handler crashed on update_id=%s", upd.get("update_id"))
            offset = upd["update_id"] + 1
            set_offset(db_path, offset)
```

- [ ] **Step 4: Run — verify all 30 bot tests pass**

Run: `cd /app && pytest tests/agents/paper_radar/test_bot.py -v`
Expected: 30 passed.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/agents/paper_radar/test_bot.py
git commit -m "feat: add run_loop with injected deps"
```

---

## Task 13: `bot.py` — wire up `main()` + module paths

**Files:**
- Modify: `bot.py`

This task glues together the real `Context`, real `get_updates`, real logging, and real env loading. No unit test — smoke-tested via `verify/verify_bot.py` in Task 15.

- [ ] **Step 1: Add constants + `main()` to `bot.py`**

Add at the top of `bot.py` (alongside existing imports):

```python
import sys
from pathlib import Path

from dotenv import load_dotenv

import telegram_client
```

Add these constants near the logger setup (after `logger = logging.getLogger(__name__)`):

```python
_MODULE_DIR = Path(__file__).resolve().parent
BOT_DB_PATH = _MODULE_DIR / "bot.sqlite"
ENV_PATH = _MODULE_DIR / ".env"
LOG_PATH = _MODULE_DIR / "bot.log"
```

Add at the bottom of `bot.py`:

```python
def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )


def _build_ctx() -> Context:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return Context(
        db_path=BOT_DB_PATH,
        whitelist=load_whitelist(),
        default_backend=os.environ.get("BOT_BACKEND", "claude").lower(),
        history_turns=int(os.environ.get("BOT_HISTORY_TURNS", "10")),
        llm_timeout=int(os.environ.get("BOT_LLM_TIMEOUT", "120")),
        send_message=lambda cid, txt: telegram_client.send_message(token, cid, txt),
        send_chat_action=lambda cid, a: telegram_client.send_chat_action(token, cid, a),
        ask_llm=ask_llm,
    )


def main() -> int:
    load_dotenv(ENV_PATH)
    _configure_logging()
    logger.info("=== paper_radar bot starting ===")
    init_chat_db(BOT_DB_PATH)
    whitelist = load_whitelist()
    if not whitelist:
        logger.error("TELEGRAM_AUTHORIZED_CHAT_IDS / TELEGRAM_CHAT_ID unset — refusing to start")
        return 1
    logger.info("whitelist=%s backend=%s", whitelist, os.environ.get("BOT_BACKEND", "claude"))

    try:
        run_loop(
            db_path=BOT_DB_PATH,
            get_updates_fn=telegram_client.get_updates,
            handler=handle_update,
            ctx_factory=_build_ctx,
        )
    except KeyboardInterrupt:
        logger.info("interrupted — exiting")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify module still imports and tests pass**

Run: `cd /app && python -c "import bot; print(bot.main.__doc__ or 'ok')"`
Expected: prints `ok` with no error.

Run: `cd /app && pytest tests/agents/paper_radar/ -v`
Expected: all tests pass (30+).

- [ ] **Step 3: Commit**

```bash
git add bot.py
git commit -m "feat: wire up bot.main() with real deps"
```

---

## Task 14: `.env.example` — new env vars

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append to `.env.example`**

Append these lines:

```
# === Telegram Q&A Bot (bot.py) ===
# 授權可用 bot 的 chat_id，CSV。未設時 fallback 到 TELEGRAM_CHAT_ID。
TELEGRAM_AUTHORIZED_CHAT_IDS=

# Bot default backend: claude (default) | gemini
BOT_BACKEND=claude

# 每輪帶入的對話對數（user+assistant = 1 輪）
BOT_HISTORY_TURNS=10

# LLM 呼叫 timeout (秒)
BOT_LLM_TIMEOUT=120
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: document bot env vars in .env.example"
```

---

## Task 15: `verify/verify_bot.py` — manual smoke

**Files:**
- Create: `verify/verify_bot.py`

- [ ] **Step 1: Create smoke script**

```python
"""Manual smoke test: start the bot in the foreground.

From /app:
    python verify/verify_bot.py

Then from your Telegram client send:
    /help
    2+2?
    /reset

Check replies arrive. Ctrl-C to exit. Not run in CI.
"""
from __future__ import annotations

import sys

from bot import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the script imports cleanly**

Run: `cd /app && python -c "import verify.verify_bot"`
Expected: no output (successful import).

- [ ] **Step 3: Commit**

```bash
git add verify/verify_bot.py
git commit -m "test: add verify/verify_bot.py smoke script"
```

---

## Task 16: `docker-compose.yml` — add bot service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Edit `docker-compose.yml`**

Append under `services:` (same indentation as `app:`):

```yaml
  paper_radar_bot:
    build:
      context: .
      dockerfile: Dockerfile
    command: python bot.py
    env_file: .env
    volumes:
      - .:/app
    environment:
      - TZ=Asia/Taipei
      - UV_PROJECT_ENVIRONMENT=/venv
      - VIRTUAL_ENV=/venv
    restart: unless-stopped
```

- [ ] **Step 2: Validate compose file syntax**

Run: `cd /app && docker compose config > /dev/null && echo OK`
Expected: `OK`. If `docker compose` is unavailable in the sandbox, skip and rely on user to bring the service up.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add paper_radar_bot service to docker-compose"
```

---

## Task 17: Final full test run + update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (paper_radar agent's sub-CLAUDE.md)

- [ ] **Step 1: Run full test suite**

Run: `cd /app && pytest tests/agents/paper_radar/ -v`
Expected: all green (should be ~40+ tests across 4 files).

- [ ] **Step 2: Update `CLAUDE.md`**

Add a new section under 結構 documenting `bot.py` / `telegram_client.py` / `chat_db.py`. Add to the 修改時要注意 list:

```
- `bot.py` 跑在獨立 process（docker-compose service `paper_radar_bot`），lifecycle 跟 cron 的 `radar.py` 分開
- `bot.py` 的 `handle_update` 用 `Context` dataclass inject 依賴（send_message / ask_llm / db_path）— 測試時塞 fake，不要改成 module-level globals
- `bot.py` 的 handler 不管出什麼錯，`run_loop` 都會推進 offset — poison message 不會卡住 queue
- `telegram_client.py` 是 `radar.py` + `bot.py` 共用，改 HTTP 細節要兩邊都測
- `chat_db.py` 用獨立的 `bot.sqlite`（不跟 `db.sqlite` 混），table: `chat_history` + `bot_state`
- Bot whitelist：`TELEGRAM_AUTHORIZED_CHAT_IDS` CSV，未設 fallback `TELEGRAM_CHAT_ID`；空集合拒絕啟動
- 新增 env：`BOT_BACKEND` / `BOT_HISTORY_TURNS` / `BOT_LLM_TIMEOUT` / `TELEGRAM_AUTHORIZED_CHAT_IDS`
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document telegram bot in CLAUDE.md"
```

- [ ] **Step 4: Manual smoke (OPTIONAL — requires live Telegram)**

Run: `cd /app && python verify/verify_bot.py`
Expected: bot starts, `=== paper_radar bot starting ===` appears; from your Telegram client send `/help`, a plain question, `/reset`; verify replies arrive.

---

## Self-Review

**Spec coverage check:**

| Spec section | Task(s) |
|---|---|
| `telegram_client.py` (send_message, send_chat_action, get_updates) | 2, 3 |
| `chat_db.py` (history + offset, separate `bot.sqlite`) | 5, 6 |
| `BOT_SYSTEM_PROMPT` + prompt assembly | 7 |
| `ask_llm` dual backend | 8 |
| whitelist auth | 9 |
| reply chunking (4096, \n\n, \n, hard-split) | 10 |
| command dispatch (/start /help /reset /backend /claude /gemini, bare cmd, unauthorized) | 11 |
| poison-message offset advance | 11 (`test_llm_error_replies_...`), 12 (`test_run_loop_advances_offset_even_when_handler_raises`) |
| long-poll loop + offset persistence | 12, 13 |
| docker-compose service | 16 |
| env vars documented | 14 |
| refactor `radar.py` to use `telegram_client` | 4 |
| smoke script | 15 |
| CLAUDE.md update | 17 |

All spec sections covered.

**Placeholder scan:** no TBD / TODO / "appropriate error handling" — all code is complete.

**Type consistency:** `Context` fields referenced identically across Tasks 11, 12, 13. `ask_llm` signature `(text, history, backend, timeout)` consistent across Tasks 8, 11, 12 (as `Callable` in Context). `send_message(chat_id, text)` callback signature consistent between Context spec and test fakes. `split_for_telegram` stable from Task 10 → used in Task 11. `get_offset` / `set_offset` consistent across Tasks 6, 12.

**Scope:** single feature, ~17 small tasks, each 2-5 min of work. TDD throughout; every non-trivial function lands with tests in the same task.
