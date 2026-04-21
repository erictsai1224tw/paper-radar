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
    reply_markup: dict | None = None,
) -> None:
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    resp = requests.post(
        _API.format(token=token, method="sendMessage"),
        json=payload,
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()


def answer_callback_query(
    token: str, callback_query_id: str, text: str = ""
) -> None:
    """ACK a callback_query so the spinning button indicator stops on the user's client."""
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]  # Telegram limit
    resp = requests.post(
        _API.format(token=token, method="answerCallbackQuery"),
        json=payload,
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()


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


def send_photo(
    token: str,
    chat_id: str,
    photo_path: str,
    caption: str | None = None,
    parse_mode: str | None = None,
) -> None:
    """Send an image file via Telegram sendPhoto. Caption limit: 1024 chars."""
    data: dict = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
        if parse_mode:
            data["parse_mode"] = parse_mode
    with open(photo_path, "rb") as fp:
        resp = requests.post(
            _API.format(token=token, method="sendPhoto"),
            data=data,
            files={"photo": fp},
            timeout=60,
        )
    resp.raise_for_status()


def send_audio(
    token: str,
    chat_id: str,
    audio_path: str,
    title: str = "",
    performer: str = "",
    caption: str | None = None,
) -> None:
    """Send an audio file via Telegram sendAudio. Max 50MB per Bot API."""
    data: dict = {"chat_id": chat_id}
    if title:
        data["title"] = title
    if performer:
        data["performer"] = performer
    if caption:
        data["caption"] = caption[:1024]
    with open(audio_path, "rb") as fp:
        resp = requests.post(
            _API.format(token=token, method="sendAudio"),
            data=data,
            files={"audio": fp},
            timeout=120,
        )
    resp.raise_for_status()
