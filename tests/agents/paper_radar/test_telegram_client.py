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
    assert mock_get.call_args.kwargs["timeout"] > 25


def test_get_updates_returns_empty_list_when_no_results():
    with patch("telegram_client.requests.get") as mock_get:
        resp = _mock_resp()
        resp.json = MagicMock(return_value={"ok": True, "result": []})
        mock_get.return_value = resp
        assert get_updates("tok", offset=0) == []


from telegram_client import send_photo


def test_send_photo_posts_file_and_caption(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_photo("tok", "42", str(img), caption="hello world")

    assert mock_post.call_args.args[0] == "https://api.telegram.org/bottok/sendPhoto"
    data = mock_post.call_args.kwargs["data"]
    assert data == {"chat_id": "42", "caption": "hello world"}
    files = mock_post.call_args.kwargs["files"]
    assert "photo" in files


def test_send_photo_truncates_caption_over_1024(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")
    long = "x" * 2000
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_photo("tok", "1", str(img), caption=long)
    assert len(mock_post.call_args.kwargs["data"]["caption"]) == 1024


def test_send_photo_omits_caption_when_none(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_photo("tok", "1", str(img))
    assert "caption" not in mock_post.call_args.kwargs["data"]


from telegram_client import send_audio


def test_send_audio_posts_file_with_metadata(tmp_path):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"\xff\xfb fake mp3")
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_audio("tok", "42", str(mp3), title="Daily Radar", performer="paper_radar")

    assert mock_post.call_args.args[0] == "https://api.telegram.org/bottok/sendAudio"
    data = mock_post.call_args.kwargs["data"]
    assert data == {"chat_id": "42", "title": "Daily Radar", "performer": "paper_radar"}
    assert "audio" in mock_post.call_args.kwargs["files"]


def test_send_audio_omits_empty_title_and_performer(tmp_path):
    mp3 = tmp_path / "x.mp3"
    mp3.write_bytes(b"fake")
    with patch("telegram_client.requests.post") as mock_post:
        mock_post.return_value = _mock_resp()
        send_audio("tok", "42", str(mp3))
    data = mock_post.call_args.kwargs["data"]
    assert data == {"chat_id": "42"}
