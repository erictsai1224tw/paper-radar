"""Telegram Q&A bot — long-polling process.

See docs/superpowers/specs/2026-04-20-telegram-qa-bot-design.md for design.
"""
from __future__ import annotations

import json
import logging
import os
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


def load_whitelist() -> set[str]:
    raw = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "").strip()
    if raw:
        return {x.strip() for x in raw.split(",") if x.strip()}
    fallback = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return {fallback} if fallback else set()


def is_authorized(chat_id: str, whitelist: set[str]) -> bool:
    return chat_id in whitelist
