"""Long-polling loop for the NOTIFY bot — handles feedback button clicks.

Runs as a separate docker-compose service. Consumes `callback_query` updates
(from the 👍/👎/🔖 buttons on paper pushes), records them to feedback.sqlite,
and ACKs the button press so the user's client shows a confirmation toast.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

import telegram_client
from feedback_db import init_feedback_db, record_feedback

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).resolve().parent
FEEDBACK_DB_PATH = _MODULE_DIR / "feedback.sqlite"
OFFSET_PATH = _MODULE_DIR / "notify_bot.offset"
ENV_PATH = _MODULE_DIR / ".env"
LOG_PATH = _MODULE_DIR / "notify_bot.log"

_ACK_TEXT = {
    "like": "👍 喜歡",
    "dislike": "👎 不喜歡",
    "save": "🔖 已收藏",
}


def _load_offset(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _save_offset(path: Path, offset: int) -> None:
    path.write_text(str(offset), encoding="utf-8")


def _parse_callback_data(data: str) -> tuple[str, str] | None:
    """Parse ``fb:{arxiv_id}:{action}`` -> (arxiv_id, action). None on malformed."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "fb":
        return None
    arxiv_id, action = parts[1], parts[2]
    if not arxiv_id or action not in ("like", "dislike", "save"):
        return None
    return arxiv_id, action


def handle_callback(
    cq: dict, token: str, db_path: Path | str
) -> None:
    """Process a single callback_query update."""
    data = cq.get("data", "")
    parsed = _parse_callback_data(data)
    if not parsed:
        logger.warning("unparseable callback_data: %r", data)
        try:
            telegram_client.answer_callback_query(token, cq["id"], "無效按鈕")
        except Exception as exc:
            logger.warning("answer_callback_query failed: %s", exc)
        return
    arxiv_id, action = parsed
    user_id = str(((cq.get("from") or {}).get("id")) or "unknown")

    try:
        record_feedback(db_path, arxiv_id, action, user_id)
    except Exception as exc:
        logger.warning("record_feedback failed for %s/%s: %s", arxiv_id, action, exc)

    try:
        telegram_client.answer_callback_query(token, cq["id"], _ACK_TEXT.get(action, "已收到"))
    except Exception as exc:
        logger.warning("answer_callback_query failed: %s", exc)
    logger.info("feedback recorded: %s %s (user %s)", arxiv_id, action, user_id)


def run_loop(
    token: str,
    db_path: Path,
    offset_path: Path,
    sleep_fn=time.sleep,
    long_poll_timeout: int = 30,
) -> None:
    offset = _load_offset(offset_path)
    while True:
        try:
            updates = telegram_client.get_updates(
                token, offset, long_poll_timeout=long_poll_timeout
            )
        except requests.RequestException as exc:
            logger.warning("getUpdates failed: %s — sleeping 5s", exc)
            sleep_fn(5)
            continue

        for upd in updates:
            cq = upd.get("callback_query")
            if cq is not None:
                try:
                    handle_callback(cq, token, db_path)
                except Exception:
                    logger.exception("handle_callback crashed on update %s", upd.get("update_id"))
            offset = upd["update_id"] + 1
            _save_offset(offset_path, offset)


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )


def main() -> int:
    load_dotenv(ENV_PATH)
    _configure_logging()
    logger.info("=== notify_bot (feedback collector) starting ===")
    init_feedback_db(FEEDBACK_DB_PATH)
    try:
        token = os.environ["TELEGRAM_NOTIFY_BOT_TOKEN"]
    except KeyError:
        logger.error("TELEGRAM_NOTIFY_BOT_TOKEN unset — refusing to start")
        return 1
    try:
        run_loop(token=token, db_path=FEEDBACK_DB_PATH, offset_path=OFFSET_PATH)
    except KeyboardInterrupt:
        logger.info("interrupted — exiting")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
