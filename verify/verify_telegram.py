"""Smoke-test notify_telegram against real Telegram Bot API.

Run from anywhere:
    python agents/paper_radar/verify/verify_telegram.py
    # or
    python /abs/path/to/agents/paper_radar/verify/verify_telegram.py
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from agents.paper_radar.radar import ENV_PATH, notify_telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

load_dotenv(ENV_PATH)


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[verify_telegram] FAIL: token/chat_id 沒設", file=sys.stderr)
        return 1

    papers = [
        {
            "arxiv_id": f"x-{i}",
            "title": f"[smoke-test #{i}] Dummy paper title for telegram verify",
            "summary_zh": (
                f"這是第 {i} 篇測試論文的第一句話，用來驗 Telegram 收訊。"
                f"第二句講為什麼有趣。"
                f"第三句跟之前方法比新在哪。"
            ),
            "tags": ["smoke-test", f"sample-{i}"],
            "upvotes": 10 * (i + 1),
            "arxiv_url": f"https://arxiv.org/abs/x-{i}",
            "hf_url": f"https://huggingface.co/papers/x-{i}",
        }
        for i in range(3)
    ]
    notify_telegram(
        papers,
        notion_url="https://www.notion.so/example",
        bot_token=token,
        chat_id=chat,
    )
    print("[verify_telegram] sent — 去手機看有沒有收到", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
