"""Run every saved /watch query once — push new matches to the notify bot.

Designed to run from cron (daily morning) and also be triggerable for a
single watch via the bot's /watch_run command.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

import paper_arxiv_search
from telegram_client import send_message
from watch_db import (
    get_seen_for_watch,
    get_watch,
    init_watch_db,
    list_watches,
    mark_seen_for_watch,
)

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).resolve().parent
WATCH_DB_PATH = _MODULE_DIR / "watch.sqlite"
ENV_PATH = _MODULE_DIR / ".env"
LOG_PATH = _MODULE_DIR / "radar.log"

_MAX_RESULTS_PER_WATCH = 5
_TG_DELAY = 1


def _render_result(idx: int, paper: dict) -> str:
    """Minimal HTML rendering for a watched paper."""
    import html as _h

    title = _h.escape(paper.get("title", "").strip())
    authors = paper.get("authors") or []
    auth = ", ".join(_h.escape(a) for a in authors[:3])
    if len(authors) > 3:
        auth += " et al."
    published = (paper.get("published") or "")[:10]
    arxiv_id = paper["arxiv_id"]
    url = _h.escape(paper.get("arxiv_url", f"https://arxiv.org/abs/{arxiv_id}"), quote=True)
    abstract = (paper.get("abstract") or "")[:220]
    if paper.get("abstract") and len(paper["abstract"]) > 220:
        abstract = abstract.rstrip() + "…"
    abstract = _h.escape(abstract)

    parts = [f"<b>{idx}. {title}</b>"]
    if auth:
        parts.append(f"<i>{auth}</i>")
    if published:
        parts.append(f"📅 {published}")
    if abstract:
        parts.append("")
        parts.append(abstract)
    parts.append("")
    parts.append(
        f'<a href="{url}">{_h.escape(arxiv_id)}</a>  '
        f'—  深入用 <code>介紹 {_h.escape(arxiv_id)}</code>'
    )
    return "\n".join(parts)


def run_one_watch(
    watch: dict,
    db_path: Path | str,
    token: str,
    chat_id: str,
    max_results: int = _MAX_RESULTS_PER_WATCH,
) -> int:
    """Search arxiv for the watch's query, push NEW papers, mark seen.

    Returns the number of new papers pushed. 0 on no new / API failure.
    """
    import html as _h

    name = watch["name"]
    query = watch["query"]

    logger.info("watch[%s] searching: %r", name, query)
    results = paper_arxiv_search.search_arxiv(query, max_results=max_results)
    if not results:
        logger.info("watch[%s] no results", name)
        return 0

    seen = get_seen_for_watch(db_path, name)
    fresh = [p for p in results if p["arxiv_id"] not in seen]
    if not fresh:
        logger.info("watch[%s] nothing new (all %d seen)", name, len(results))
        return 0

    header = (
        f"🔖 <b>watch <code>{_h.escape(name)}</code></b>  "
        f"(<code>{_h.escape(query)}</code>) — {len(fresh)} 篇新"
    )
    try:
        send_message(token, chat_id, header, parse_mode="HTML")
    except Exception as exc:
        logger.warning("watch[%s] header send failed: %s", name, exc)
        return 0
    for i, paper in enumerate(fresh, start=1):
        time.sleep(_TG_DELAY)
        try:
            send_message(token, chat_id, _render_result(i, paper), parse_mode="HTML")
        except Exception as exc:
            logger.warning(
                "watch[%s] result %s send failed: %s",
                name, paper.get("arxiv_id"), exc,
            )

    mark_seen_for_watch(db_path, name, [p["arxiv_id"] for p in fresh])
    return len(fresh)


def run_all_watches(db_path: Path | str, token: str, chat_id: str) -> int:
    """Iterate every watch; return total new papers pushed."""
    total = 0
    for w in list_watches(db_path):
        try:
            total += run_one_watch(w, db_path, token, chat_id)
        except Exception:
            logger.exception("watch[%s] crashed", w.get("name"))
    return total


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
    logger.info("=== watch runner starting ===")
    init_watch_db(WATCH_DB_PATH)
    try:
        token = os.environ["TELEGRAM_NOTIFY_BOT_TOKEN"]
        chat_id = os.environ["TELEGRAM_NOTIFY_CHAT_ID"]
    except KeyError as exc:
        logger.error("missing env %s — abort", exc)
        return 1
    total = run_all_watches(WATCH_DB_PATH, token, chat_id)
    logger.info("=== watch runner done: %d new papers pushed ===", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
