"""Telegram Q&A bot — long-polling process.

See docs/superpowers/specs/2026-04-20-telegram-qa-bot-design.md for design.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

import telegram_client
from prompts import build_chat_prompt

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).resolve().parent
BOT_DB_PATH = _MODULE_DIR / "bot.sqlite"
ENV_PATH = _MODULE_DIR / ".env"
LOG_PATH = _MODULE_DIR / "bot.log"

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


def load_whitelist() -> set[str]:
    raw = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "").strip()
    if not raw:
        return set()
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_authorized(chat_id: str, whitelist: set[str]) -> bool:
    return chat_id in whitelist


_TG_LIMIT = 4096


def split_for_telegram(text: str) -> list[str]:
    """Split ``text`` into Telegram-safe chunks (<=4096 chars each).

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
        boundary_len = 2 if remaining[cut:cut + 2] == "\n\n" else 1
        remaining = remaining[cut + boundary_len:]
    if remaining:
        chunks.append(remaining)
    return chunks


from dataclasses import dataclass
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
        backend = cmd[1:]
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


import time

import requests

from chat_db import get_offset, init_chat_db, set_offset


def run_loop(
    db_path: Path,
    get_updates_fn: Callable[[str, int, int], list[dict]],
    handler: Callable[[dict, Context], None],
    ctx_factory: Callable[[], Context],
    sleep_fn: Callable[[float], None] = time.sleep,
    long_poll_timeout: int = 30,
) -> None:
    """Long-poll loop. Injects getUpdates + handler so tests can fake them."""
    token = os.environ["TELEGRAM_QA_BOT_TOKEN"]
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


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )


def _build_ctx() -> Context:
    token = os.environ["TELEGRAM_QA_BOT_TOKEN"]
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
        logger.error("TELEGRAM_AUTHORIZED_CHAT_IDS unset — refusing to start")
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
