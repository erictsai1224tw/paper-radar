"""Telegram Q&A bot — long-polling process.

See docs/superpowers/specs/2026-04-20-telegram-qa-bot-design.md for design.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

import telegram_client
from prompts import build_chat_prompt

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).resolve().parent
BOT_DB_PATH = _MODULE_DIR / "bot.sqlite"
ENV_PATH = _MODULE_DIR / ".env"
LOG_PATH = _MODULE_DIR / "bot.log"
SUMMARIES_PATH = _MODULE_DIR / "summaries.json"
PAPERS_MD_DIR = _MODULE_DIR / "papers_md"

_CLAUDE_DISALLOWED_TOOLS = "WebSearch,WebFetch,Bash,Read,Write,Edit,Glob,Grep,TodoWrite,Task"

_CLAUDE_MODEL = "sonnet"
_GEMINI_MODEL = "gemini-3-flash-preview"


def _run_claude_bot(prompt: str, timeout: int) -> str:
    argv = [
        "claude",
        "-p", prompt,
        "--model", _CLAUDE_MODEL,
        "--output-format", "json",
        "--max-turns", "1",
        "--disallowedTools", _CLAUDE_DISALLOWED_TOOLS,
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True,
        timeout=timeout, check=True,
    )
    return json.loads(proc.stdout)["result"]


def _run_gemini_bot(prompt: str, timeout: int) -> str:
    argv = [
        "gemini",
        "-p", prompt,
        "--model", _GEMINI_MODEL,
        "--output-format", "json",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True,
        timeout=timeout, check=True,
    )
    return json.loads(proc.stdout)["response"]


_BACKENDS = {"claude": _run_claude_bot, "gemini": _run_gemini_bot}


def ask_llm(
    text: str,
    history: list[dict],
    backend: str,
    timeout: int,
    todays_papers: list[dict] | None = None,
    paper_fulltext: str | None = None,
) -> str:
    """Shell out to `claude -p` / `gemini -p` with history + papers context."""
    runner = _BACKENDS.get(backend)
    if runner is None:
        raise ValueError(f"unknown backend {backend!r}")
    prompt = build_chat_prompt(
        history=history,
        current=text,
        todays_papers=todays_papers,
        paper_fulltext=paper_fulltext,
    )
    return runner(prompt, timeout)


_PAPER_INDEX_RE = re.compile(r"第\s*(\d+|[一二三四五六七八九十])\s*篇")
_ZH_NUMS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def detect_paper_index(text: str) -> int | None:
    """Extract a 1-based paper index from text like '第 7 篇' / '第七篇論文'."""
    m = _PAPER_INDEX_RE.search(text)
    if not m:
        return None
    g = m.group(1)
    return int(g) if g.isdigit() else _ZH_NUMS.get(g)


# Python 3 \w is Unicode-aware, so 中文字 count as word chars and \b won't
# trigger between a Chinese character and a digit (e.g. "介紹2604.16044" misses
# with a \b-bounded pattern). Use digit-only negative lookarounds instead —
# they still prevent matching the middle of a longer numeric run.
_ARXIV_ID_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?!\d)")


def detect_arxiv_id(text: str) -> str | None:
    """Find an arxiv_id like '2604.16044' anywhere in the message."""
    m = _ARXIV_ID_RE.search(text)
    return m.group(1) if m else None


def detect_paper_by_title(text: str, papers: list[dict]) -> str | None:
    """Return the arxiv_id whose title has the longest substring overlap with ``text``.

    Checks each paper's title against the user text (case-insensitive). Requires
    at least 12 contiguous characters of overlap (lowercased) so stray mentions
    don't trigger false positives. Returns ``None`` when nothing qualifies.
    """
    if not text or not papers:
        return None
    t_lower = text.lower()
    best_id: str | None = None
    best_len = 11  # floor — need > 11 chars to beat
    for p in papers:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        title_lower = title.lower()
        # cheap heuristic: longest common substring via a simple sliding check —
        # avoid importing difflib for such a small comparison
        for size in range(min(len(title_lower), 80), best_len, -1):
            for i in range(len(title_lower) - size + 1):
                chunk = title_lower[i:i + size]
                if chunk in t_lower:
                    best_len = size
                    best_id = p.get("arxiv_id")
                    break
            if best_len == size and best_id == p.get("arxiv_id"):
                break
    return best_id


def load_paper_markdown_by_id(
    arxiv_id: str, papers_md_dir: Path | str
) -> str | None:
    """Read papers_md/{arxiv_id}.md if it exists. None otherwise."""
    if not arxiv_id:
        return None
    path = Path(papers_md_dir) / f"{arxiv_id}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def fetch_paper_markdown_on_demand(
    arxiv_id: str, papers_md_dir: Path | str
) -> str | None:
    """Download + convert a paper to markdown on demand, then return its text.

    Used when a user asks about an arxiv_id whose markdown isn't cached yet.
    Wraps ``paper_markdown.fetch_pdf_as_markdown`` — the same code path the
    daily radar uses — so the result lands at the normal cache location and
    subsequent lookups hit instantly. Returns ``None`` on any failure (PDF
    download, markitdown conversion) so the bot can degrade gracefully.
    """
    if not arxiv_id:
        return None
    try:
        from paper_markdown import fetch_pdf_as_markdown
        path = fetch_pdf_as_markdown(arxiv_id, papers_md_dir)
    except Exception as exc:
        logger.warning("on-demand fetch failed for %s: %s", arxiv_id, exc)
        return None
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def load_paper_fulltext(
    index: int, papers: list[dict], papers_md_dir: Path | str
) -> str | None:
    """Read papers_md/{arxiv_id}.md for the 1-based N-th paper; None if unavailable."""
    if not (1 <= index <= len(papers)):
        return None
    arxiv_id = papers[index - 1].get("arxiv_id")
    return load_paper_markdown_by_id(arxiv_id, papers_md_dir)


def load_todays_papers() -> list[dict]:
    """Load the last paper_radar push (just today's batch from summaries.json)."""
    try:
        data = json.loads(SUMMARIES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("load_todays_papers failed: %s", exc)
        return []


def load_recent_papers(days: int = 7) -> list[dict]:
    """Return papers from the last ``days`` days (archive + today's batch), deduped."""
    from weekly_rollup import ARCHIVE_PATH, load_recent_papers as _load_archive
    recent = _load_archive(ARCHIVE_PATH, days=days)
    # merge today's summaries (which may not yet be in archive mid-pipeline)
    recent.extend(load_todays_papers())
    seen: dict[str, dict] = {}
    for p in recent:
        aid = p.get("arxiv_id")
        if aid:
            seen[aid] = p  # later wins — that's fine
    return list(seen.values())


def load_whitelist() -> set[str]:
    raw = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "").strip()
    if not raw:
        return set()
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_authorized(chat_id: str, whitelist: set[str]) -> bool:
    return chat_id in whitelist


_TG_LIMIT = 4096


def split_for_telegram(text: str) -> list[str]:
    """Split ``text`` into Telegram-safe chunks (<=4096 chars each).

    Prefers splitting at the last \\n\\n before the limit, then the last \\n,
    then hard-splits at exactly 4096.
    """
    chunks: list[str] = []
    remaining = text
    while len(remaining) > _TG_LIMIT:
        window = remaining[:_TG_LIMIT]
        cut = window.rfind("\n\n")
        if cut == -1:
            cut = window.rfind("\n")
        if cut == -1:
            cut = _TG_LIMIT
            chunks.append(remaining[:cut])
            remaining = remaining[cut:]
            continue
        chunks.append(remaining[:cut])
        boundary_len = 2 if remaining[cut:cut + 2] == "\n\n" else 1
        remaining = remaining[cut + boundary_len:]
    if remaining:
        chunks.append(remaining)
    return chunks


from dataclasses import dataclass
from typing import Callable

from chat_db import append_turn, clear_history, get_history


@dataclass
class Context:
    db_path: Path
    whitelist: set[str]
    default_backend: str
    history_turns: int
    llm_timeout: int
    send_message: Callable[[str, str], None]
    send_chat_action: Callable[[str, str], None]
    ask_llm: Callable[..., str]
    typing_interval: float = 4.0
    todays_papers: list[dict] = None         # today's batch — drives '第 N 篇'
    recent_papers: list[dict] = None         # last 7 days — drives title + id lookup
    papers_md_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.todays_papers is None:
            self.todays_papers = []
        if self.recent_papers is None:
            self.recent_papers = []


_HELP_TEXT = (
    "可用指令：\n"
    "/help — 顯示這段\n"
    "/reset — 清空對話歷史\n"
    "/backend — 顯示目前預設 backend\n"
    "/claude <q> — 這則強制用 claude\n"
    "/gemini <q> — 這則強制用 gemini\n"
    "直接傳訊息：用預設 backend 回答，帶歷史"
)


def handle_update(upd: dict, ctx: Context) -> None:
    msg = upd.get("message") or {}
    text = msg.get("text")
    chat_id_raw = (msg.get("chat") or {}).get("id")
    if not text or chat_id_raw is None:
        return
    chat_id = str(chat_id_raw)

    if not is_authorized(chat_id, ctx.whitelist):
        logger.warning("unauthorized chat_id=%s", chat_id)
        ctx.send_message(chat_id, "unauthorized")
        return

    if text.startswith("/"):
        _handle_command(chat_id, text, ctx)
        return

    _handle_free_form(chat_id, text, ctx.default_backend, ctx)


def _handle_command(chat_id: str, text: str, ctx: Context) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        ctx.send_message(chat_id, _HELP_TEXT)
        return
    if cmd == "/reset":
        clear_history(ctx.db_path, chat_id)
        ctx.send_message(chat_id, "歷史已清空")
        return
    if cmd == "/backend":
        ctx.send_message(chat_id, f"目前 backend: {ctx.default_backend}")
        return
    if cmd in ("/claude", "/gemini"):
        if not arg.strip():
            ctx.send_message(chat_id, "需要問題內容")
            return
        backend = cmd[1:]
        _handle_free_form(chat_id, arg, backend, ctx)
        return

    ctx.send_message(chat_id, f"未知指令：{cmd}\n{_HELP_TEXT}")


def _typing_pump(chat_id: str, ctx: Context, stop: "threading.Event") -> None:
    """Keep firing ``sendChatAction("typing")`` until ``stop`` is set.

    Telegram's typing indicator expires after ~5s, so we re-fire every
    ``ctx.typing_interval`` seconds (default 4) until the LLM returns.
    """
    while True:
        try:
            ctx.send_chat_action(chat_id, "typing")
        except Exception as exc:
            logger.warning("send_chat_action pump failed: %s", exc)
        if stop.wait(ctx.typing_interval):
            return


def _handle_free_form(chat_id: str, text: str, backend: str, ctx: Context) -> None:
    import threading

    stop_pump = threading.Event()
    pump = threading.Thread(
        target=_typing_pump, args=(chat_id, ctx, stop_pump), daemon=True
    )
    pump.start()
    try:
        history = get_history(ctx.db_path, chat_id, limit=ctx.history_turns * 2)

        paper_fulltext: str | None = None
        matched_id: str | None = None
        idx = detect_paper_index(text)
        if idx is not None and ctx.papers_md_dir is not None:
            paper_fulltext = load_paper_fulltext(idx, ctx.todays_papers, ctx.papers_md_dir)
            if paper_fulltext is not None and 1 <= idx <= len(ctx.todays_papers):
                matched_id = ctx.todays_papers[idx - 1].get("arxiv_id")
        if paper_fulltext is None and ctx.papers_md_dir is not None:
            aid = detect_arxiv_id(text)
            if aid:
                paper_fulltext = load_paper_markdown_by_id(aid, ctx.papers_md_dir)
                if paper_fulltext is None:
                    # Not cached yet — download + convert on demand so the bot
                    # can answer deep questions about any paper the user names.
                    paper_fulltext = fetch_paper_markdown_on_demand(aid, ctx.papers_md_dir)
                if paper_fulltext is not None:
                    matched_id = aid
        if paper_fulltext is None and ctx.papers_md_dir is not None:
            aid = detect_paper_by_title(text, ctx.recent_papers)
            if aid:
                paper_fulltext = load_paper_markdown_by_id(aid, ctx.papers_md_dir)
                if paper_fulltext is not None:
                    matched_id = aid
        logger.info(
            "chat=%s backend=%s matched_id=%s fulltext_chars=%s",
            chat_id, backend, matched_id, len(paper_fulltext) if paper_fulltext else 0,
        )

        try:
            reply = ctx.ask_llm(
                text, history, backend, ctx.llm_timeout,
                todays_papers=ctx.todays_papers,
                paper_fulltext=paper_fulltext,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "ask_llm(%s) non-zero exit for chat=%s: rc=%s stderr=%r stdout=%r",
                backend, chat_id, exc.returncode, (exc.stderr or "")[:500], (exc.stdout or "")[:500],
            )
            ctx.send_message(chat_id, "⏱️ 回覆失敗，請再試一次")
            return
        except Exception as exc:
            logger.warning("ask_llm(%s) failed for chat=%s: %s", backend, chat_id, exc)
            ctx.send_message(chat_id, "⏱️ 回覆失敗，請再試一次")
            return

        append_turn(ctx.db_path, chat_id, "user", text)
        append_turn(ctx.db_path, chat_id, "assistant", reply)

        for chunk in split_for_telegram(reply):
            try:
                ctx.send_message(chat_id, chunk)
            except Exception as exc:
                logger.warning("send_message failed for chat=%s: %s", chat_id, exc)
                return
    finally:
        stop_pump.set()
        pump.join(timeout=1)


import time

import requests

from chat_db import get_offset, init_chat_db, set_offset


def run_loop(
    db_path: Path,
    get_updates_fn: Callable[[str, int, int], list[dict]],
    handler: Callable[[dict, Context], None],
    ctx_factory: Callable[[], Context],
    sleep_fn: Callable[[float], None] = time.sleep,
    long_poll_timeout: int = 30,
) -> None:
    """Long-poll loop. Injects getUpdates + handler so tests can fake them."""
    token = os.environ["TELEGRAM_QA_BOT_TOKEN"]
    offset = get_offset(db_path)

    while True:
        try:
            updates = get_updates_fn(token, offset, long_poll_timeout)
        except requests.RequestException as exc:
            logger.warning("getUpdates failed: %s — sleeping 5s", exc)
            sleep_fn(5)
            continue

        ctx = ctx_factory()
        for upd in updates:
            try:
                handler(upd, ctx)
            except Exception:
                logger.exception("handler crashed on update_id=%s", upd.get("update_id"))
            offset = upd["update_id"] + 1
            set_offset(db_path, offset)


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )


def _build_ctx() -> Context:
    token = os.environ["TELEGRAM_QA_BOT_TOKEN"]
    # Re-read summaries + 7-day archive each ctx build so fresh pushes and older
    # papers (still cached in papers_md/) are both reachable.
    today_papers = load_todays_papers()
    recent = load_recent_papers(days=7)
    return Context(
        db_path=BOT_DB_PATH,
        whitelist=load_whitelist(),
        default_backend=os.environ.get("BOT_BACKEND", "claude").lower(),
        history_turns=int(os.environ.get("BOT_HISTORY_TURNS", "10")),
        llm_timeout=int(os.environ.get("BOT_LLM_TIMEOUT", "120")),
        send_message=lambda cid, txt: telegram_client.send_message(token, cid, txt),
        send_chat_action=lambda cid, a: telegram_client.send_chat_action(token, cid, a),
        ask_llm=ask_llm,
        todays_papers=today_papers,
        recent_papers=recent,
        papers_md_dir=PAPERS_MD_DIR,
    )


def main() -> int:
    load_dotenv(ENV_PATH)
    _configure_logging()
    logger.info("=== paper_radar bot starting ===")
    init_chat_db(BOT_DB_PATH)
    whitelist = load_whitelist()
    if not whitelist:
        logger.error("TELEGRAM_AUTHORIZED_CHAT_IDS unset — refusing to start")
        return 1
    logger.info("whitelist=%s backend=%s", whitelist, os.environ.get("BOT_BACKEND", "claude"))

    try:
        run_loop(
            db_path=BOT_DB_PATH,
            get_updates_fn=telegram_client.get_updates,
            handler=handle_update,
            ctx_factory=_build_ctx,
        )
    except KeyboardInterrupt:
        logger.info("interrupted — exiting")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
