"""Shared HTML rendering for paper results (search / similar / refs / watch).

Used by bot._build_search_result_message and watch_runner._render_result.
Keep the function pure so both sync and cron contexts can reuse it.
"""
from __future__ import annotations

import html as _html

TITLE_MAX = 80
ABSTRACT_SNIPPET = 260


def render_paper_card(idx: int, paper: dict, ctas: list[str] | None = None) -> str:
    """Render one paper as a Telegram-HTML card.

    ``paper`` fields (all optional except title / arxiv_id):
    - arxiv_id, title, abstract (or tldr as fallback), authors,
      published (ISO, first 10 chars rendered), arxiv_url
    ``ctas``: pre-formatted HTML snippets appended after the arxiv link,
    joined with two spaces. Lets callers customize 「深入用 …」 hints.
    """
    title = _html.escape((paper.get("title") or "").strip()[:TITLE_MAX])
    abstract = (paper.get("abstract") or paper.get("tldr") or "").strip()
    if len(abstract) > ABSTRACT_SNIPPET:
        abstract = abstract[:ABSTRACT_SNIPPET].rstrip() + "…"
    abstract = _html.escape(abstract)
    authors = paper.get("authors") or []
    auth_text = ", ".join(_html.escape(a) for a in authors[:3])
    if len(authors) > 3:
        auth_text += " et al."
    published = (paper.get("published") or "")[:10]
    arxiv_id = paper.get("arxiv_id", "?")
    url = _html.escape(
        paper.get("arxiv_url", f"https://arxiv.org/abs/{arxiv_id}"), quote=True
    )

    parts = [f"<b>{idx}. {title}</b>"]
    if auth_text:
        parts.append(f"<i>{auth_text}</i>")
    if published:
        parts.append(f"📅 {published}")
    if abstract:
        parts.append("")
        parts.append(abstract)
    parts.append("")
    link = f'<a href="{url}">{_html.escape(arxiv_id)}</a>'
    if ctas:
        parts.append(link + "  —  " + "  ".join(ctas))
    else:
        parts.append(link)
    return "\n".join(parts)
