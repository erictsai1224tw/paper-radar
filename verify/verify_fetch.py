"""Print HF daily_papers raw response — quick check API is alive."""

from __future__ import annotations

import json
import logging
import sys

from agents.paper_radar.radar import fetch_papers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    papers = fetch_papers(limit=30)
    print(f"[verify_fetch] got {len(papers)} papers", file=sys.stderr)
    for i, p in enumerate(papers[:5]):
        print(f"  #{i} ⬆{p['upvotes']:>3} {p['title'][:80]}", file=sys.stderr)
    print(json.dumps(papers[0], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
