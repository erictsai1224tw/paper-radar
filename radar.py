"""AI Paper Radar orchestrator.

See docs/plans/paper.md for feature spec,
docs/superpowers/specs/2026-04-20-paper-radar-design.md for repo integration.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

from db import get_seen_ids, init_db, mark_seen
from prompts import NOTION_PUSH_PROMPT, SUMMARIZE_PROMPT

_MODULE_DIR = Path(__file__).resolve().parent

# === Config ===
TOP_N = 8
HF_API_LIMIT = 30
HF_API_URL = "https://huggingface.co/api/daily_papers"
CLAUDE_MODEL = "sonnet"
CLAUDE_TIMEOUT = 120  # seconds per paper
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
DB_PATH = _MODULE_DIR / "db.sqlite"
SUMMARIES_PATH = _MODULE_DIR / "summaries.json"
ENV_PATH = _MODULE_DIR / ".env"
LOG_PATH = _MODULE_DIR / "radar.log"

logger = logging.getLogger(__name__)


def fetch_papers(
    limit: int = HF_API_LIMIT,
    timeout: int = 30,
    max_retries: int = 3,
    retry_delay: int = 5,
) -> list[dict]:
    """抓 HF daily papers 並按 upvotes 降序排序。

    Returns list of dicts with keys:
        arxiv_id, title, tldr, upvotes, arxiv_url, hf_url
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(
                HF_API_URL, params={"limit": limit}, timeout=timeout
            )
            resp.raise_for_status()
            raw = resp.json()
            break
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("fetch_papers attempt %d/%d failed: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(retry_delay)
    else:
        assert last_exc is not None
        raise last_exc

    papers = [_normalize(item) for item in raw]
    papers.sort(key=lambda p: p["upvotes"], reverse=True)
    return papers


def _normalize(item: dict) -> dict:
    paper = item["paper"]
    arxiv_id = paper["id"]
    return {
        "arxiv_id": arxiv_id,
        "title": paper["title"],
        "tldr": paper.get("summary", ""),
        "upvotes": paper.get("upvotes", 0),
        "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
        "hf_url": f"https://huggingface.co/papers/{arxiv_id}",
    }


def dedup(papers: list[dict], db_path: Path | str, top_n: int = TOP_N) -> list[dict]:
    """過濾已見過的 paper，回傳前 top_n 篇（保留輸入順序）。"""
    seen = get_seen_ids(db_path)
    fresh = [p for p in papers if p["arxiv_id"] not in seen]
    return fresh[:top_n]


def summarize(paper: dict) -> dict:
    """跑 `claude -p` 摘要，回傳加上 summary_zh + tags 的 paper dict。

    失敗時 fallback 成用 tldr 當 summary_zh、空 tags，log 警告不 abort。
    """
    prompt = SUMMARIZE_PROMPT.format(
        title=paper["title"],
        abstract=paper["tldr"],
    )
    argv = [
        "claude",
        "-p", prompt,
        "--model", CLAUDE_MODEL,
        "--output-format", "json",
        "--max-turns", "1",
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            check=True,
        )
        outer = json.loads(proc.stdout)
        raw_result = outer["result"].strip()
        # Strip markdown code fences if Claude wraps the JSON
        if raw_result.startswith("```"):
            raw_result = raw_result.split("\n", 1)[1]  # drop ```json line
            raw_result = raw_result.rsplit("```", 1)[0].strip()
        inner = json.loads(raw_result)
        summary_zh = inner["summary_zh"]
        tags = inner.get("tags", [])
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as exc:
        logger.warning(
            "summarize failed for %s: %s — falling back to tldr",
            paper["arxiv_id"], exc,
        )
        summary_zh = paper["tldr"]
        tags = []

    return {**paper, "summary_zh": summary_zh, "tags": tags}


def push_to_notion(
    summaries: list[dict],
    summaries_path: Path | str,
    parent_page_url: str,
) -> str:
    """把 summaries 丟給 Claude + Notion MCP 建 page，回傳 page URL。

    失敗時 raise（Notion step 失敗要讓上層決定 retry/skip/abort）。
    """
    summaries_path = Path(summaries_path)
    summaries_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    prompt = NOTION_PUSH_PROMPT.format(
        summaries_path=str(summaries_path),
        parent_page_url=parent_page_url,
        date=date.today().isoformat(),
    )
    argv = [
        "claude",
        "-p", prompt,
        "--model", CLAUDE_MODEL,
        "--output-format", "json",
        "--max-turns", "10",
        "--allowedTools", "Read,mcp__claude_ai_Notion__*",
    ]
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT * 10,  # Notion 流程 multi-turn 要給更多時間
        check=True,
    )
    outer = json.loads(proc.stdout)
    raw_result = outer["result"].strip()
    # Strip markdown code fences if Claude wraps the JSON (same pattern as summarize)
    if raw_result.startswith("```"):
        raw_result = raw_result.split("\n", 1)[1]  # drop ```json line
        raw_result = raw_result.rsplit("```", 1)[0].strip()
    inner = json.loads(raw_result)
    return inner["notion_url"]


_TITLE_MAX = 80
_TELEGRAM_MSG_DELAY = 1  # seconds between messages to avoid rate limiting


def _build_paper_message(idx: int, paper: dict) -> str:
    """組成單篇 paper 的 Telegram 訊息 (HTML mode)。"""
    import html

    title = html.escape(paper["title"][:_TITLE_MAX])
    summary = html.escape(paper.get("summary_zh", "").strip())
    tags = " · ".join(html.escape(t) for t in paper.get("tags", []))
    upvotes = paper.get("upvotes", 0)
    arxiv_url = html.escape(paper.get("arxiv_url", ""), quote=True)

    parts = [f"<b>{idx}. {title}</b>"]
    if summary:
        parts.append(summary)
    meta_bits: list[str] = []
    if tags:
        meta_bits.append(f"🏷️ {tags}")
    if upvotes:
        meta_bits.append(f"⬆ {upvotes}")
    if meta_bits:
        parts.append("  ".join(meta_bits))
    if arxiv_url:
        parts.append(f'🔗 <a href="{arxiv_url}">arxiv</a>')
    return "\n".join(parts)


def _send_telegram_message(url: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    resp.raise_for_status()


def notify_telegram(
    papers: list[dict],
    notion_url: str,
    bot_token: str,
    chat_id: str,
    today: str | None = None,
) -> None:
    """每篇 paper 各發一則 Telegram 訊息，最後附 Notion 連結。

    失敗時 log warning 但不 raise（Notion 已寫好）。
    """
    import html

    if today is None:
        today = date.today().isoformat()

    url = TELEGRAM_API.format(token=bot_token)
    n = len(papers)

    try:
        _send_telegram_message(
            url, chat_id,
            f"📚 <b>AI Radar {html.escape(today)}</b> — {n} 篇新論文",
        )
    except Exception as exc:
        logger.warning("notify_telegram header failed: %s", exc)
        return

    for i, paper in enumerate(papers, start=1):
        time.sleep(_TELEGRAM_MSG_DELAY)
        try:
            _send_telegram_message(url, chat_id, _build_paper_message(i, paper))
        except Exception as exc:
            logger.warning("notify_telegram paper %s failed: %s", paper.get("arxiv_id"), exc)

    time.sleep(_TELEGRAM_MSG_DELAY)
    try:
        _send_telegram_message(
            url, chat_id,
            f'<a href="{html.escape(notion_url, quote=True)}">👉 看 Notion 完整整理</a>',
        )
    except Exception as exc:
        logger.warning("notify_telegram notion link failed: %s", exc)


def main() -> int:
    load_dotenv(ENV_PATH)
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(),
        ],
        force=True,
    )
    logger.info("=== AI Paper Radar starting ===")

    try:
        db_path = DB_PATH
        init_db(db_path)

        papers = fetch_papers()
        logger.info("fetched %d papers", len(papers))

        fresh = dedup(papers, db_path, top_n=TOP_N)
        logger.info("after dedup: %d fresh papers", len(fresh))
        if not fresh:
            logger.info("nothing new today — exit")
            return 0

        summaries = [summarize(p) for p in fresh]
        logger.info("summarized %d papers", len(summaries))

        parent = os.environ["NOTION_PARENT_PAGE_URL"]
        notion_url = push_to_notion(summaries, SUMMARIES_PATH, parent)
        logger.info("notion page: %s", notion_url)

        notify_telegram(
            summaries,
            notion_url,
            bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
        )

        mark_seen(db_path, summaries)
        logger.info("=== done ===")
        return 0
    except Exception:
        logger.exception("pipeline failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
