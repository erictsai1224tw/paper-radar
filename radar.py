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
from paper_figure import fetch_first_figure
from paper_markdown import fetch_pdf_as_markdown
from paper_s2 import fetch_s2_metadata
from prompts import EXPLAIN_FIGURE_PROMPT, NOTION_PUSH_PROMPT, SUMMARIZE_PROMPT
from telegram_client import send_message as _tg_send
from telegram_client import send_photo as _tg_send_photo

_MODULE_DIR = Path(__file__).resolve().parent

# === Config ===
TOP_N = 8
HF_API_LIMIT = 30
HF_API_URL = "https://huggingface.co/api/daily_papers"
CLAUDE_MODEL = "sonnet"
GEMINI_MODEL = "gemini-3-flash-preview"
LLM_TIMEOUT = 120  # seconds per paper (applies to claude & gemini)
CLAUDE_TIMEOUT = LLM_TIMEOUT  # kept for push_to_notion backward compat
DB_PATH = _MODULE_DIR / "db.sqlite"
SUMMARIES_PATH = _MODULE_DIR / "summaries.json"
PAPERS_MD_DIR = _MODULE_DIR / "papers_md"
PAPERS_FIG_DIR = _MODULE_DIR / "papers_fig"
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


def _extract_year(item: dict, arxiv_id: str) -> int | None:
    """arxiv_id YYMM.NNNNN 前綴為論文原始年份；HF publishedAt 是「加進 daily 的日期」不準。"""
    try:
        yy = int(arxiv_id.split(".")[0][:2])
        return 2000 + yy
    except (ValueError, IndexError):
        pass
    pub = item.get("publishedAt") or item.get("paper", {}).get("publishedAt")
    if isinstance(pub, str) and len(pub) >= 4 and pub[:4].isdigit():
        return int(pub[:4])
    return None


def _normalize(item: dict) -> dict:
    paper = item["paper"]
    arxiv_id = paper["id"]
    authors = [
        a.get("name", "")
        for a in paper.get("authors", [])
        if isinstance(a, dict) and a.get("name")
    ]
    return {
        "arxiv_id": arxiv_id,
        "title": paper["title"],
        "tldr": paper.get("summary", ""),  # fallback abstract, will be overwritten by summarize()
        "year": _extract_year(item, arxiv_id),
        "upvotes": paper.get("upvotes", 0),
        "authors": authors,
        "github_url": paper.get("githubRepo") or "",
        "github_stars": paper.get("githubStars") or 0,
        "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
        "hf_url": f"https://huggingface.co/papers/{arxiv_id}",
    }


def load_watchlist() -> list[str]:
    """Parse AUTHOR_WATCHLIST env (CSV of name substrings). Case-insensitive match."""
    raw = os.environ.get("AUTHOR_WATCHLIST", "").strip()
    if not raw:
        return []
    return [n.strip().lower() for n in raw.split(",") if n.strip()]


def is_watched(authors: list[str], watchlist: list[str]) -> bool:
    if not watchlist:
        return False
    joined = " | ".join(authors).lower()
    return any(needle in joined for needle in watchlist)


def dedup(papers: list[dict], db_path: Path | str, top_n: int = TOP_N) -> list[dict]:
    """過濾已見過的 paper，回傳前 top_n 篇（保留輸入順序）。"""
    seen = get_seen_ids(db_path)
    fresh = [p for p in papers if p["arxiv_id"] not in seen]
    return fresh[:top_n]


def _strip_json_fence(raw: str) -> str:
    """若 LLM 把 JSON 包在 ```json ... ``` fence 裡，剝掉 fence。"""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]  # drop ```json line
        raw = raw.rsplit("```", 1)[0].strip()
    return raw


def _run_claude_summarize(prompt: str) -> str:
    """跑 claude -p，回傳 outer JSON 裡的 result 字串（已剝 fence）。"""
    argv = [
        "claude",
        "-p", prompt,
        "--model", CLAUDE_MODEL,
        "--output-format", "json",
        "--max-turns", "1",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True,
        timeout=LLM_TIMEOUT, check=True,
    )
    return _strip_json_fence(json.loads(proc.stdout)["result"])


def _run_gemini_summarize(prompt: str) -> str:
    """跑 gemini -p，回傳 outer JSON 裡的 response 字串（已剝 fence）。"""
    argv = [
        "gemini",
        "-p", prompt,
        "--model", GEMINI_MODEL,
        "--output-format", "json",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True,
        timeout=LLM_TIMEOUT, check=True,
    )
    return _strip_json_fence(json.loads(proc.stdout)["response"])


_SUMMARIZER_RUNNERS = {
    "claude": _run_claude_summarize,
    "gemini": _run_gemini_summarize,
}


def explain_figure(
    paper: dict, caption: str, provider: str | None = None
) -> str:
    """Turn a Figure 1 caption into a short Chinese blurb via claude/gemini.

    Falls back to the raw caption (truncated) on any failure.
    """
    if provider is None:
        provider = os.environ.get("SUMMARIZER", "claude").lower()
    runner = _SUMMARIZER_RUNNERS.get(provider) or _run_claude_summarize

    prompt = EXPLAIN_FIGURE_PROMPT.format(
        title=paper["title"], caption=caption,
    )
    try:
        return runner(prompt).strip()
    except subprocess.SubprocessError as exc:
        logger.warning(
            "explain_figure(%s) failed for %s: %s — falling back to raw caption",
            provider, paper["arxiv_id"], exc,
        )
        return caption[:200]


def summarize(paper: dict, provider: str | None = None) -> dict:
    """用 `claude -p` 或 `gemini -p` 做結構化摘要。

    加到 paper dict 的欄位：tldr (覆蓋 abstract), venue, strengths, limitations, tags
    provider 優先序：顯式參數 > SUMMARIZER 環境變數 > "claude"。
    失敗時 fallback：tldr 沿用 abstract，strengths/limitations 空、tags 空。
    """
    if provider is None:
        provider = os.environ.get("SUMMARIZER", "claude").lower()
    runner = _SUMMARIZER_RUNNERS.get(provider)
    if runner is None:
        logger.warning("unknown SUMMARIZER %r — falling back to claude", provider)
        runner = _run_claude_summarize
        provider = "claude"

    prompt = SUMMARIZE_PROMPT.format(
        title=paper["title"],
        abstract=paper["tldr"],
    )
    try:
        inner = json.loads(runner(prompt))
        tldr = inner["tldr"]
        venue = inner.get("venue", "")
        strengths = inner.get("strengths", [])
        limitations = inner.get("limitations", [])
        open_questions = inner.get("open_questions", [])
        future_work = inner.get("future_work", [])
        tags = inner.get("tags", [])
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as exc:
        logger.warning(
            "summarize(%s) failed for %s: %s — falling back to abstract",
            provider, paper["arxiv_id"], exc,
        )
        tldr = paper["tldr"]
        venue = ""
        strengths = []
        limitations = []
        open_questions = []
        future_work = []
        tags = []

    return {
        **paper,
        "tldr": tldr,
        "venue": venue,
        "strengths": strengths,
        "limitations": limitations,
        "open_questions": open_questions,
        "future_work": future_work,
        "tags": tags,
    }


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
        timeout=LLM_TIMEOUT * 10,  # Notion 流程 multi-turn 要給更多時間
        check=True,
    )
    inner = json.loads(_strip_json_fence(json.loads(proc.stdout)["result"]))
    return inner["notion_url"]


_TITLE_MAX = 80
_TELEGRAM_MSG_DELAY = 1  # seconds between messages to avoid rate limiting


def _build_paper_message(idx: int, paper: dict) -> str:
    """組成單篇 paper 的 Telegram 訊息 (HTML mode)。"""
    import html

    star = "⭐ " if paper.get("watched") else ""
    title = html.escape(paper["title"][:_TITLE_MAX])
    tldr = html.escape(paper.get("tldr", "").strip())
    tags = " · ".join(html.escape(t) for t in paper.get("tags", []))
    upvotes = paper.get("upvotes", 0)
    year = paper.get("year")
    venue = (paper.get("venue") or "").strip()
    arxiv_url = html.escape(paper.get("arxiv_url", ""), quote=True)
    github_url = html.escape(paper.get("github_url", ""), quote=True)
    cites = paper.get("citation_count", 0)
    inf_cites = paper.get("influential_citation_count", 0)

    parts = [f"<b>{star}{idx}. {title}</b>"]
    if tldr:
        parts.append(tldr)
    meta_bits: list[str] = []
    if venue:
        meta_bits.append(html.escape(venue))
    if year:
        meta_bits.append(str(year))
    if cites:
        meta_bits.append(f"📎 {cites} cites" + (f" ({inf_cites}✨)" if inf_cites else ""))
    if tags:
        meta_bits.append(f"🏷️ {tags}")
    if upvotes:
        meta_bits.append(f"⬆ {upvotes}")
    if meta_bits:
        parts.append("  ".join(meta_bits))
    links: list[str] = []
    if arxiv_url:
        links.append(f'🔗 <a href="{arxiv_url}">arxiv</a>')
    if github_url:
        links.append(f'💻 <a href="{github_url}">code</a>')
    if links:
        parts.append("  ".join(links))
    return "\n".join(parts)


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

    n = len(papers)

    try:
        _tg_send(
            bot_token, chat_id,
            f"📚 <b>AI Radar {html.escape(today)}</b> — {n} 篇新論文",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("notify_telegram header failed: %s", exc)
        return

    for i, paper in enumerate(papers, start=1):
        time.sleep(_TELEGRAM_MSG_DELAY)
        try:
            _tg_send(bot_token, chat_id, _build_paper_message(i, paper), parse_mode="HTML")
        except Exception as exc:
            logger.warning("notify_telegram paper %s failed: %s", paper.get("arxiv_id"), exc)

        fig_path = paper.get("figure_path")
        if fig_path and Path(fig_path).exists():
            time.sleep(_TELEGRAM_MSG_DELAY)
            fig_caption = paper.get("figure_explain") or paper.get("figure_caption") or ""
            try:
                _tg_send_photo(bot_token, chat_id, fig_path, caption=fig_caption)
            except Exception as exc:
                logger.warning("notify_telegram figure %s failed: %s", paper.get("arxiv_id"), exc)

    time.sleep(_TELEGRAM_MSG_DELAY)
    try:
        _tg_send(
            bot_token, chat_id,
            f'<a href="{html.escape(notion_url, quote=True)}">👉 看 Notion 完整整理</a>',
            parse_mode="HTML",
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

        provider = os.environ.get("SUMMARIZER", "claude").lower()
        logger.info("summarizing with %s", provider)
        summaries = [summarize(p, provider=provider) for p in fresh]
        logger.info("summarized %d papers", len(summaries))

        watchlist = load_watchlist()
        if watchlist:
            logger.info("watchlist active: %s", watchlist)
        for s in summaries:
            s2 = fetch_s2_metadata(s["arxiv_id"])
            if s2:
                if s2.get("venue"):
                    s["venue"] = s2["venue"]
                s["citation_count"] = s2["citation_count"]
                s["influential_citation_count"] = s2["influential_citation_count"]
                logger.info(
                    "s2[%s] venue=%r cites=%s/%s",
                    s["arxiv_id"], s2["venue"],
                    s2["citation_count"], s2["influential_citation_count"],
                )
            s["watched"] = is_watched(s.get("authors", []), watchlist)

        logger.info("caching paper markdowns to %s", PAPERS_MD_DIR)
        for s in summaries:
            md_path = fetch_pdf_as_markdown(s["arxiv_id"], PAPERS_MD_DIR)
            if md_path:
                logger.info("markdown cached: %s", md_path.name)

        logger.info("extracting Figure 1 images to %s", PAPERS_FIG_DIR)
        for s in summaries:
            fig = fetch_first_figure(s["arxiv_id"], PAPERS_FIG_DIR)
            if fig:
                png_path, caption = fig
                s["figure_path"] = str(png_path)
                s["figure_caption"] = caption
                if caption:
                    s["figure_explain"] = explain_figure(s, caption, provider=provider)
                    logger.info(
                        "figure[%s]: %s  explain=%r",
                        s["arxiv_id"], png_path.name, s["figure_explain"][:80],
                    )

        parent = os.environ["NOTION_PARENT_PAGE_URL"]
        notion_url = push_to_notion(summaries, SUMMARIES_PATH, parent)
        logger.info("notion page: %s", notion_url)

        notify_telegram(
            summaries,
            notion_url,
            bot_token=os.environ["TELEGRAM_NOTIFY_BOT_TOKEN"],
            chat_id=os.environ["TELEGRAM_NOTIFY_CHAT_ID"],
        )

        mark_seen(db_path, summaries)
        try:
            from weekly_rollup import ARCHIVE_PATH, archive_papers
            archive_papers(summaries, ARCHIVE_PATH)
            logger.info("archived %d papers to %s", len(summaries), ARCHIVE_PATH.name)
        except Exception as exc:
            logger.warning("archive_papers failed: %s", exc)
        logger.info("=== done ===")
        return 0
    except Exception:
        logger.exception("pipeline failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
