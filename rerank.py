"""Minimal re-ranker that reorders papers by predicted preference.

Uses per-tag like rates computed from Telegram 👍/👎 feedback. No ML libs —
just Laplace-smoothed ratios. Dead simple, interpretable, works with ~20 data
points. When a paper has no tags (or all its tags are unseen), it scores 0.5
(neutral) so it neither gains nor loses position.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from feedback_db import get_all_feedback


def _tag_like_rates(feedback: list[dict], tag_lookup: dict[str, list[str]]) -> dict[str, float]:
    """Per-tag like rate with +1 Laplace smoothing.

    ``tag_lookup`` is arxiv_id → tags[] so we can project feedback onto tags.
    """
    tag_likes: dict[str, int] = defaultdict(int)
    tag_dislikes: dict[str, int] = defaultdict(int)
    for fb in feedback:
        if fb["action"] not in ("like", "dislike"):
            continue
        tags = tag_lookup.get(fb["arxiv_id"], [])
        for t in tags:
            if fb["action"] == "like":
                tag_likes[t] += 1
            else:
                tag_dislikes[t] += 1
    all_tags = set(tag_likes) | set(tag_dislikes)
    return {
        t: (tag_likes[t] + 1) / (tag_likes[t] + tag_dislikes[t] + 2)
        for t in all_tags
    }


def score_paper(paper: dict, rates: dict[str, float]) -> float:
    """Mean like-rate across the paper's tags; 0.5 when nothing matches."""
    tags = paper.get("tags", []) or []
    scored = [rates[t] for t in tags if t in rates]
    return sum(scored) / len(scored) if scored else 0.5


def rerank_by_preference(
    papers: list[dict],
    feedback_db_path: Path | str,
    history_db_path: Path | str,
    min_samples: int,
) -> list[dict]:
    """Return ``papers`` re-ordered by predicted preference.

    Does nothing (returns input) when total feedback < ``min_samples`` — with
    a tiny sample the tag rates are too noisy to beat HF upvotes.

    ``history_db_path`` is the dedup SQLite; we pull past papers' tags from the
    currently-archived summaries file (not stored in dedup DB). The caller
    passes the historical tag_lookup explicitly via the feedback_db path.
    """
    feedback = get_all_feedback(feedback_db_path)
    if len(feedback) < min_samples:
        return papers

    # Build tag_lookup from the current batch (simple baseline). A richer
    # lookup could read papers_archive.jsonl for historical tag info; kept
    # minimal here — the returned rates will update as more feedback flows in.
    tag_lookup = {p["arxiv_id"]: p.get("tags", []) for p in papers}
    rates = _tag_like_rates(feedback, tag_lookup)
    if not rates:
        return papers

    scored = sorted(
        papers,
        key=lambda p: score_paper(p, rates),
        reverse=True,
    )
    return scored


def rerank_by_preference_with_archive(
    papers: list[dict],
    feedback_db_path: Path | str,
    archive_lookup: dict[str, list[str]],
    min_samples: int,
) -> list[dict]:
    """Same as ``rerank_by_preference`` but receives an explicit archive lookup.

    ``archive_lookup`` maps arxiv_id → tags[] for historical papers (e.g.
    loaded from ``papers_archive.jsonl``). This is what actually trains the
    rates — fresh papers don't have feedback yet.
    """
    feedback = get_all_feedback(feedback_db_path)
    if len(feedback) < min_samples:
        return papers
    rates = _tag_like_rates(feedback, archive_lookup)
    if not rates:
        return papers
    return sorted(papers, key=lambda p: score_paper(p, rates), reverse=True)
