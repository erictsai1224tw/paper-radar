"""Smoke-test summarize() against real `claude -p` CLI.

Run from worktree root:
    python agents/paper_radar/verify/verify_summarize.py
"""

from __future__ import annotations

import json
import logging
import sys

from agents.paper_radar.radar import summarize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SAMPLE = {
    "arxiv_id": "2410.00000",
    "title": "Attention Is All You Need",
    "tldr": (
        "The dominant sequence transduction models are based on complex recurrent or "
        "convolutional neural networks. We propose a new simple network architecture, "
        "the Transformer, based solely on attention mechanisms."
    ),
    "upvotes": 999,
    "arxiv_url": "https://arxiv.org/abs/2410.00000",
    "hf_url": "https://huggingface.co/papers/2410.00000",
}


def main() -> int:
    print(f"[verify_summarize] sending paper: {SAMPLE['title']}", file=sys.stderr)
    out = summarize(SAMPLE)
    print(json.dumps(out, ensure_ascii=False, indent=2))

    if not out.get("summary_zh"):
        print("[verify_summarize] FAIL: no summary_zh", file=sys.stderr)
        return 1
    if out["summary_zh"] == SAMPLE["tldr"]:
        print("[verify_summarize] WARN: fallback triggered (summarize didn't parse)", file=sys.stderr)
        return 2
    print("[verify_summarize] OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
