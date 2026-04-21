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


_MD_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_loaded_markdown(text: str) -> str:
    """Strip C0 control chars that sometimes leak from markitdown's PDF path.

    Primarily defends against embedded null bytes which make subprocess.run
    reject the argv (ValueError: embedded null byte) when the fulltext gets
    concatenated into the LLM prompt.
    """
    return _MD_CONTROL_CHAR_RE.sub("", text)


# --- markdown → Telegram-HTML rendering -----------------------------------

import html as _html

_CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_HEADER_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# Math: strip the $ delimiters, keep content. LaTeX markup stays but beats "$$...$$"
_DOLLAR_DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_DOLLAR_INLINE_RE = re.compile(r"(?<!\\)\$([^$\n]{1,200})\$")
_TABLE_SEP_RE = re.compile(r"^\|[\s\-|:]+\|\s*$", re.MULTILINE)


def markdown_to_telegram_html(text: str) -> str:
    """Convert a markdown reply into Telegram's ``parse_mode=HTML`` subset.

    Supported: ``**bold**``, `` `code` ``, ``` ``` fence ```, ``# header``
    (rendered as bold), ``[text](url)`` links. Markdown tables get their
    separator rows stripped; LaTeX math has the $ delimiters removed and
    content kept (so ``$\\alpha$`` → ``\\alpha``; the upstream prompt
    already tells the LLM to prefer Unicode).
    """
    # Protect code spans first (no conversions inside them) via placeholders.
    code_blocks: list[str] = []
    def _stash_block(m: re.Match) -> str:
        code_blocks.append(m.group(1).rstrip("\n"))
        return f"\x00CB{len(code_blocks) - 1}\x00"
    text = _CODE_BLOCK_RE.sub(_stash_block, text)

    inline_codes: list[str] = []
    def _stash_inline(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"
    text = _INLINE_CODE_RE.sub(_stash_inline, text)

    # HTML-escape the rest so user text never forges tags.
    text = _html.escape(text)

    # Drop table separator rows, they look like "|---|---|" walls otherwise.
    text = _TABLE_SEP_RE.sub("", text)

    # Headers → bold.
    text = _HEADER_RE.sub(r"<b>\1</b>", text)
    # Bold.
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    # Links.
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)
    # Strip $ math delimiters (keep inner text).
    text = _DOLLAR_DISPLAY_RE.sub(r"\1", text)
    text = _DOLLAR_INLINE_RE.sub(r"\1", text)

    # Restore code spans with escaped content.
    for i, body in enumerate(code_blocks):
        text = text.replace(
            f"\x00CB{i}\x00",
            f"<pre><code>{_html.escape(body)}</code></pre>",
        )
    for i, body in enumerate(inline_codes):
        text = text.replace(
            f"\x00IC{i}\x00",
            f"<code>{_html.escape(body)}</code>",
        )
    return text


def load_paper_markdown_by_id(
    arxiv_id: str, papers_md_dir: Path | str
) -> str | None:
    """Read papers_md/{arxiv_id}.md if it exists. None otherwise."""
    if not arxiv_id:
        return None
    path = Path(papers_md_dir) / f"{arxiv_id}.md"
    try:
        return _sanitize_loaded_markdown(path.read_text(encoding="utf-8"))
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
        return _sanitize_loaded_markdown(path.read_text(encoding="utf-8"))
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
    send_document: Callable[..., None] | None = None   # for /notebook

    def __post_init__(self) -> None:
        if self.todays_papers is None:
            self.todays_papers = []
        if self.recent_papers is None:
            self.recent_papers = []


_HELP_TEXT = (
    "<b>可用指令</b>\n"
    "<code>/help</code> — 顯示這段\n"
    "<code>/reset</code> — 清空對話歷史\n"
    "<code>/backend</code> — 顯示目前預設 backend\n"
    "<code>/claude &lt;q&gt;</code> — 這則強制用 claude\n"
    "<code>/gemini &lt;q&gt;</code> — 這則強制用 gemini\n"
    "<code>/search &lt;query&gt;</code> — arxiv 搜尋某領域最新 5 篇\n"
    "<code>/similar &lt;paper&gt;</code> — 列出語意相似的 paper（S2 推薦）\n"
    "<code>/refs &lt;paper&gt;</code> — 引用 / 被引用清單（S2 citation graph）\n"
    "<code>/notebook &lt;paper&gt;</code> — 拿 NotebookLM 用的 URL + markdown 檔\n"
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
    if cmd == "/notebook":
        _handle_notebook(chat_id, arg, ctx)
        return
    if cmd == "/search":
        _handle_search(chat_id, arg, ctx)
        return
    if cmd == "/similar":
        _handle_similar(chat_id, arg, ctx)
        return
    if cmd == "/refs":
        _handle_refs(chat_id, arg, ctx)
        return

    ctx.send_message(chat_id, f"未知指令：{cmd}\n{_HELP_TEXT}")


def _push_paper_list(chat_id: str, header: str, papers: list[dict], ctx: Context) -> None:
    """Send a header + one formatted message per paper."""
    try:
        ctx.send_message(chat_id, header)
    except Exception as exc:
        logger.warning("header send failed: %s", exc)
        return
    for i, p in enumerate(papers, start=1):
        try:
            ctx.send_message(chat_id, _build_search_result_message(i, p))
        except Exception as exc:
            logger.warning("paper send failed %s: %s", p.get("arxiv_id"), exc)


def _handle_similar(chat_id: str, arg: str, ctx: Context) -> None:
    """/similar <paper ref> — Semantic Scholar recommendation neighbours."""
    if not arg.strip():
        ctx.send_message(
            chat_id,
            "用法：<code>/similar 2604.16044</code> 或 <code>/similar 第 1 篇</code>",
        )
        return
    aid = _resolve_paper_ref(arg, ctx)
    if not aid:
        ctx.send_message(chat_id, "找不到這篇 paper。試 arxiv_id 或完整標題。")
        return
    try:
        ctx.send_chat_action(chat_id, "typing")
    except Exception as exc:
        logger.warning("send_chat_action failed: %s", exc)

    from paper_s2 import fetch_recommendations
    import html as _h

    results = fetch_recommendations(aid, limit=5)
    if not results:
        ctx.send_message(
            chat_id,
            f"（S2 對 <code>{_h.escape(aid)}</code> 沒推薦資料，可能是太新未索引）",
        )
        return
    header = f"🔁 <b>與 <code>{_h.escape(aid)}</code> 相似的 paper</b> — {len(results)} 篇"
    _push_paper_list(chat_id, header, results, ctx)


def _handle_refs(chat_id: str, arg: str, ctx: Context) -> None:
    """/refs <paper ref> — list papers referenced by + papers citing the target."""
    if not arg.strip():
        ctx.send_message(chat_id, "用法：<code>/refs 2604.16044</code>")
        return
    aid = _resolve_paper_ref(arg, ctx)
    if not aid:
        ctx.send_message(chat_id, "找不到這篇 paper。試 arxiv_id 或完整標題。")
        return
    try:
        ctx.send_chat_action(chat_id, "typing")
    except Exception as exc:
        logger.warning("send_chat_action failed: %s", exc)

    from paper_s2 import fetch_citations, fetch_references
    import html as _h

    refs = fetch_references(aid, limit=5)
    cites = fetch_citations(aid, limit=5)
    if not refs and not cites:
        ctx.send_message(
            chat_id,
            f"（S2 對 <code>{_h.escape(aid)}</code> 沒 citation graph，可能太新未索引）",
        )
        return

    if refs:
        header = (
            f"📖 <b><code>{_h.escape(aid)}</code> 引用的 paper</b> — {len(refs)} 篇"
        )
        _push_paper_list(chat_id, header, refs, ctx)
    if cites:
        header = (
            f"📎 <b>引用 <code>{_h.escape(aid)}</code> 的 paper</b> — {len(cites)} 篇"
        )
        _push_paper_list(chat_id, header, cites, ctx)


_SEARCH_MAX_RESULTS = 5
_SEARCH_ABSTRACT_SNIPPET = 260


def _build_search_result_message(idx: int, paper: dict) -> str:
    import html as _h
    title = _h.escape(paper["title"])
    abstract_raw = paper.get("abstract") or ""
    if len(abstract_raw) > _SEARCH_ABSTRACT_SNIPPET:
        abstract_raw = abstract_raw[:_SEARCH_ABSTRACT_SNIPPET].rstrip() + "…"
    abstract = _h.escape(abstract_raw)
    authors = paper.get("authors") or []
    auth_text = ", ".join(_h.escape(a) for a in authors[:3])
    if len(authors) > 3:
        auth_text += " et al."
    published = (paper.get("published") or "")[:10]  # YYYY-MM-DD
    arxiv_id = paper["arxiv_id"]
    url = _h.escape(paper.get("arxiv_url", f"https://arxiv.org/abs/{arxiv_id}"), quote=True)

    lines = [f"<b>{idx}. {title}</b>"]
    if auth_text:
        lines.append(f"<i>{auth_text}</i>")
    if published:
        lines.append(f"📅 {published}")
    if abstract:
        lines.append("")
        lines.append(abstract)
    lines.append("")
    lines.append(
        f'<a href="{url}">{_h.escape(arxiv_id)}</a>  '
        f'—  深入用 <code>介紹 {_h.escape(arxiv_id)}</code>  '
        f'或 <code>/notebook {_h.escape(arxiv_id)}</code>'
    )
    return "\n".join(lines)


def _handle_search(chat_id: str, query: str, ctx: Context) -> None:
    """Search arxiv for the given free-text query, push up to 5 most recent."""
    if not query.strip():
        ctx.send_message(chat_id, "用法：<code>/search efficient diffusion sampling</code>")
        return

    try:
        ctx.send_chat_action(chat_id, "typing")
    except Exception as exc:
        logger.warning("send_chat_action failed: %s", exc)

    from paper_arxiv_search import search_arxiv

    results = search_arxiv(query, max_results=_SEARCH_MAX_RESULTS)
    if not results:
        ctx.send_message(chat_id, f"（arxiv 搜 <code>{query}</code> 沒結果或 API 被限流，稍後再試）")
        return

    import html as _h
    header = f"🔎 <b>arxiv 搜尋：</b><code>{_h.escape(query)}</code> — {len(results)} 篇最新"
    try:
        ctx.send_message(chat_id, header)
    except Exception as exc:
        logger.warning("search header failed: %s", exc)
        return

    for i, paper in enumerate(results, start=1):
        msg = _build_search_result_message(i, paper)
        try:
            ctx.send_message(chat_id, msg)
        except Exception as exc:
            logger.warning("search result %s failed: %s", paper.get("arxiv_id"), exc)


def _resolve_paper_ref(text: str, ctx: Context) -> str | None:
    """Resolve a paper reference from message text using bot's detectors.

    Tries, in order: '第 N 篇' (today's batch) → arxiv_id → title substring.
    Returns the arxiv_id or None.
    """
    idx = detect_paper_index(text)
    if idx is not None and 1 <= idx <= len(ctx.todays_papers):
        aid = ctx.todays_papers[idx - 1].get("arxiv_id")
        if aid:
            return aid
    aid = detect_arxiv_id(text)
    if aid:
        return aid
    return detect_paper_by_title(text, ctx.recent_papers)


def _build_notebook_message(paper: dict | None, arxiv_id: str) -> str:
    """Compose the URL bundle for the NotebookLM source list."""
    import html as _h

    lines = ["📓 <b>NotebookLM 餵給你：</b>\n"]
    lines.append(f'📄 PDF: <a href="https://arxiv.org/pdf/{_h.escape(arxiv_id, quote=True)}">arxiv.org/pdf/{_h.escape(arxiv_id)}</a>')
    lines.append(f'📖 Abstract: <a href="https://arxiv.org/abs/{_h.escape(arxiv_id, quote=True)}">arxiv.org/abs/{_h.escape(arxiv_id)}</a>')
    lines.append(f'🤗 HF: <a href="https://huggingface.co/papers/{_h.escape(arxiv_id, quote=True)}">huggingface.co/papers/{_h.escape(arxiv_id)}</a>')
    if paper and (gh := (paper.get("github_url") or "").strip()):
        gh_e = _h.escape(gh, quote=True)
        lines.append(f'💻 Code: <a href="{gh_e}">{_h.escape(gh)}</a>')
    lines.append("")
    lines.append("上面連結都貼進 NotebookLM「Add source」，再把下面的 .md 檔拉進去當 source，就能在 NotebookLM 裡跟這篇深度對話 / 生 audio overview。")
    return "\n".join(lines)


def _handle_notebook(chat_id: str, arg: str, ctx: Context) -> None:
    """Hand the user a NotebookLM-ready source bundle: URLs + cached markdown file."""
    if not arg.strip():
        ctx.send_message(chat_id, "用法：<code>/notebook 2604.16044</code> 或 <code>/notebook 第 1 篇</code>")
        return

    aid = _resolve_paper_ref(arg, ctx)
    if not aid:
        ctx.send_message(chat_id, "找不到這篇。試 <code>/notebook &lt;arxiv_id&gt;</code> 或完整標題。")
        return

    # Locate a matching paper metadata (github_url etc.) if we have it.
    paper_meta: dict | None = None
    for p in (ctx.todays_papers or []) + (ctx.recent_papers or []):
        if p.get("arxiv_id") == aid:
            paper_meta = p
            break

    # Send the URL bundle as an HTML message.
    try:
        ctx.send_message(chat_id, _build_notebook_message(paper_meta, aid))
    except Exception as exc:
        logger.warning("notebook message failed: %s", exc)
        return

    if ctx.papers_md_dir is None or ctx.send_document is None:
        return

    # Load / fetch the markdown file so the user can attach it to NotebookLM.
    md_path = Path(ctx.papers_md_dir) / f"{aid}.md"
    if not md_path.exists():
        text = fetch_paper_markdown_on_demand(aid, ctx.papers_md_dir)
        if text is None or not md_path.exists():
            ctx.send_message(chat_id, "（抓取 PDF 失敗，只能給 URL — 你直接丟 arxiv PDF 給 NotebookLM 也行）")
            return

    try:
        ctx.send_document(chat_id, str(md_path), filename=f"{aid}.md")
    except Exception as exc:
        logger.warning("notebook send_document failed: %s", exc)


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

        rendered = markdown_to_telegram_html(reply)
        for chunk in split_for_telegram(rendered):
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
        send_message=lambda cid, txt: telegram_client.send_message(token, cid, txt, parse_mode="HTML"),
        send_chat_action=lambda cid, a: telegram_client.send_chat_action(token, cid, a),
        ask_llm=ask_llm,
        todays_papers=today_papers,
        recent_papers=recent,
        papers_md_dir=PAPERS_MD_DIR,
        send_document=lambda cid, path, filename=None: telegram_client.send_document(
            token, cid, path, filename=filename,
        ),
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
