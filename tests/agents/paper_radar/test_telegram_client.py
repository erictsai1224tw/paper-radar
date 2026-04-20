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
