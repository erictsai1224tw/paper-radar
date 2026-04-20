"""Smoke-test push_to_notion against real Notion MCP + Claude Code connector.

Run from anywhere:
    python agents/paper_radar/verify/verify_notion.py
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from agents.paper_radar.radar import ENV_PATH, SUMMARIES_PATH, push_to_notion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

load_dotenv(ENV_PATH)

SAMPLES = [
    {
        "arxiv_id": "2410.00001",
        "title": "Smoke Test Paper A",
        "summary_zh": "這篇做的是冒煙測試。為了確認 Notion MCP 連得上。跟之前比沒進步，但能 work。",
        "tags": ["smoke-test"],
        "upvotes": 1,
        "arxiv_url": "https://arxiv.org/abs/2410.00001",
        "hf_url": "https://huggingface.co/papers/2410.00001",
    },
    {
        "arxiv_id": "2410.00002",
        "title": "Smoke Test Paper B",
        "summary_zh": "第二篇也是冒煙測試。為了驗 multi-entry layout。跟單篇的差別是要多一個 divider。",
        "tags": ["smoke-test"],
        "upvotes": 2,
        "arxiv_url": "https://arxiv.org/abs/2410.00002",
        "hf_url": "https://huggingface.co/papers/2410.00002",
    },
]


def main() -> int:
    parent = os.getenv("NOTION_PARENT_PAGE_URL")
    if not parent:
        print("[verify_notion] FAIL: NOTION_PARENT_PAGE_URL 沒設", file=sys.stderr)
        return 1

    print(f"[verify_notion] pushing 2 samples under {parent}", file=sys.stderr)
    try:
        url = push_to_notion(
            SAMPLES,
            summaries_path=SUMMARIES_PATH,
            parent_page_url=parent,
        )
    except Exception as exc:
        print(f"[verify_notion] FAIL: {exc}", file=sys.stderr)
        return 1

    print(f"[verify_notion] OK: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
