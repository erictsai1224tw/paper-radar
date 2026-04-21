"""Weekly paper rollup: cluster the past N days of pushed papers by theme.

Run via cron every Sunday morning. Reads papers_archive.jsonl, asks Claude to
cluster by theme, sends a Telegram digest via the notify bot.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from prompts import WEEKLY_CLUSTER_PROMPT, format_paper_block
from telegram_client import send_message

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).resolve().parent
ARCHIVE_PATH = _MODULE_DIR / "papers_archive.jsonl"
ENV_PATH = _MODULE_DIR / ".env"
LOG_PATH = _MODULE_DIR / "radar.log"

_CLAUDE_MODEL = "sonnet"
_LLM_TIMEOUT = 180
_DAYS_WINDOW = 7
_TG_DELAY = 1


def archive_papers(summaries: list[dict], archive_path: Path | str) -> None:
    """Append each paper (with archived_at timestamp) to a JSONL archive."""
    archive_path = Path(archive_path)
    now = datetime.now().isoformat(timespec="seconds")
    with archive_path.open("a", encoding="utf-8") as fp:
        for s in summaries:
            line = {**s, "archived_at": now}
            fp.write(json.dumps(line, ensure_ascii=False) + "\n")


def load_recent_papers(
    archive_path: Path | str, days: int = _DAYS_WINDOW, now: datetime | None = None
) -> list[dict]:
    """Return papers archived within the last ``days`` days, oldest-first."""
    archive_path = Path(archive_path)
    if not archive_path.exists():
        return []
    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    out: list[dict] = []
    with archive_path.open(encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = p.get("archived_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if dt >= cutoff:
                out.append(p)
    return out


def _strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0].strip()
    return raw


def _build_cluster_prompt(papers: list[dict]) -> str:
    return WEEKLY_CLUSTER_PROMPT.format(paper_block=format_paper_block(papers))


def cluster_papers(papers: list[dict]) -> list[dict]:
    """Ask Claude to cluster papers into 3-5 themes.

    Returns list of {theme, summary, arxiv_ids}. Returns single synthetic
    cluster on LLM failure (so the digest still goes out).
    """
    if not papers:
        return []
    prompt = _build_cluster_prompt(papers)
    argv = [
        "claude", "-p", prompt,
        "--model", _CLAUDE_MODEL,
        "--output-format", "json",
        "--max-turns", "1",
        "--disallowedTools", "WebSearch,WebFetch,Bash,Read,Write,Edit,Glob,Grep",
    ]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=_LLM_TIMEOUT, check=True,
        )
        inner = json.loads(_strip_json_fence(json.loads(proc.stdout)["result"]))
        return inner.get("clusters", [])
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("cluster_papers failed: %s — falling back to single cluster", exc)
        return [{
            "theme": "本週論文",
            "summary": f"共 {len(papers)} 篇，LLM clustering 失敗請手動看 Notion",
            "arxiv_ids": [p["arxiv_id"] for p in papers],
        }]


_TITLE_MAX = 60


def build_rollup_message(clusters: list[dict], papers: list[dict], week_end: str) -> str:
    """Render clusters as an HTML-formatted Telegram message."""
    import html

    by_id = {p["arxiv_id"]: p for p in papers}
    parts = [f"📚 <b>Weekly Paper Rollup — {html.escape(week_end)}</b>  ({len(papers)} papers)"]
    for i, c in enumerate(clusters, 1):
        theme = html.escape(str(c.get("theme", f"Theme {i}")))
        summary = html.escape(str(c.get("summary", "")))
        parts.append(f"\n<b>{i}. {theme}</b>")
        if summary:
            parts.append(summary)
        for aid in c.get("arxiv_ids", []):
            p = by_id.get(aid)
            if not p:
                continue
            title = html.escape(p["title"][:_TITLE_MAX])
            url = html.escape(p.get("arxiv_url", f"https://arxiv.org/abs/{aid}"), quote=True)
            parts.append(f'  • <a href="{url}">{title}</a>')
    return "\n".join(parts)


def main() -> int:
    load_dotenv(ENV_PATH)
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )
    logger.info("=== weekly rollup starting ===")

    papers = load_recent_papers(ARCHIVE_PATH, days=_DAYS_WINDOW)
    if not papers:
        logger.info("no papers archived in the last %d days — exit", _DAYS_WINDOW)
        return 0

    # Deduplicate by arxiv_id in case a paper was pushed multiple times
    dedup: dict[str, dict] = {}
    for p in papers:
        dedup[p["arxiv_id"]] = p
    papers = list(dedup.values())
    logger.info("weekly rollup: %d unique papers", len(papers))

    clusters = cluster_papers(papers)
    logger.info("weekly rollup: %d clusters", len(clusters))

    msg = build_rollup_message(clusters, papers, date.today().isoformat())
    token = os.environ["TELEGRAM_NOTIFY_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_NOTIFY_CHAT_ID"]
    # Telegram 4096-char limit — if msg exceeds, send in chunks by paragraph
    from bot import split_for_telegram
    for chunk in split_for_telegram(msg):
        try:
            send_message(token, chat_id, chunk, parse_mode="HTML")
        except Exception as exc:
            logger.warning("send weekly chunk failed: %s", exc)
    logger.info("=== weekly rollup done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
