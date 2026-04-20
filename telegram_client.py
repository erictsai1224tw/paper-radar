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
