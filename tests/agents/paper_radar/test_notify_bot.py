"""Tests for notify_bot (feedback collector loop + handler)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from feedback_db import get_all_feedback, init_feedback_db
from notify_bot import _parse_callback_data, handle_callback, run_loop


@pytest.mark.parametrize(
    "data,expected",
    [
        ("fb:2501.1:like", ("2501.1", "like")),
        ("fb:2501.1:dislike", ("2501.1", "dislike")),
        ("fb:2501.1:save", ("2501.1", "save")),
        ("fb:2501.1:bogus", None),
        ("other:2501.1:like", None),
        ("fb::like", None),
        ("", None),
        ("fb:2501.1", None),
    ],
)
def test_parse_callback_data(data, expected):
    assert _parse_callback_data(data) == expected


def test_handle_callback_records_feedback_and_acks(tmp_db: Path):
    init_feedback_db(tmp_db)
    cq = {
        "id": "cbq1",
        "data": "fb:2501.1:like",
        "from": {"id": 42},
    }
    with patch("notify_bot.telegram_client.answer_callback_query") as mock_ack:
        handle_callback(cq, "tok", tmp_db)

    rows = get_all_feedback(tmp_db)
    assert len(rows) == 1
    assert rows[0]["arxiv_id"] == "2501.1"
    assert rows[0]["action"] == "like"
    assert rows[0]["user_id"] == "42"
    mock_ack.assert_called_once()
    assert "喜歡" in mock_ack.call_args.args[2]


def test_handle_callback_acks_but_skips_record_on_malformed_data(tmp_db: Path):
    init_feedback_db(tmp_db)
    cq = {"id": "cbq2", "data": "garbage", "from": {"id": 42}}
    with patch("notify_bot.telegram_client.answer_callback_query") as mock_ack:
        handle_callback(cq, "tok", tmp_db)
    assert get_all_feedback(tmp_db) == []
    mock_ack.assert_called_once()
    assert "無效" in mock_ack.call_args.args[2]


def test_run_loop_processes_callback_and_advances_offset(tmp_db: Path, tmp_path: Path):
    init_feedback_db(tmp_db)
    offset_file = tmp_path / "off"

    def fake_updates(token, offset, long_poll_timeout):
        if offset == 0:
            return [{
                "update_id": 5,
                "callback_query": {"id": "cb5", "data": "fb:x:like", "from": {"id": 7}},
            }]
        raise KeyboardInterrupt

    with patch("notify_bot.telegram_client.get_updates", side_effect=fake_updates), \
         patch("notify_bot.telegram_client.answer_callback_query"):
        try:
            run_loop(token="tok", db_path=tmp_db, offset_path=offset_file, sleep_fn=lambda s: None)
        except KeyboardInterrupt:
            pass

    assert [r["arxiv_id"] for r in get_all_feedback(tmp_db)] == ["x"]
    assert offset_file.read_text() == "6"


def test_run_loop_ignores_non_callback_updates(tmp_db: Path, tmp_path: Path):
    init_feedback_db(tmp_db)
    offset_file = tmp_path / "off"

    def fake_updates(token, offset, long_poll_timeout):
        if offset == 0:
            return [{"update_id": 3, "message": {"text": "random text message"}}]
        raise KeyboardInterrupt

    with patch("notify_bot.telegram_client.get_updates", side_effect=fake_updates):
        try:
            run_loop(token="tok", db_path=tmp_db, offset_path=offset_file, sleep_fn=lambda s: None)
        except KeyboardInterrupt:
            pass

    assert get_all_feedback(tmp_db) == []
    assert offset_file.read_text() == "4"


def test_run_loop_sleeps_on_network_error(tmp_db: Path, tmp_path: Path):
    import requests as rq
    init_feedback_db(tmp_db)
    offset_file = tmp_path / "off"
    calls = [0]
    slept = []

    def fake_updates(token, offset, long_poll_timeout):
        calls[0] += 1
        if calls[0] == 1:
            raise rq.RequestException("boom")
        raise KeyboardInterrupt

    with patch("notify_bot.telegram_client.get_updates", side_effect=fake_updates):
        try:
            run_loop(token="tok", db_path=tmp_db, offset_path=offset_file, sleep_fn=lambda s: slept.append(s))
        except KeyboardInterrupt:
            pass
    assert slept == [5]
