"""Manual smoke test: start the bot in the foreground.

From /app:
    python verify/verify_bot.py

Then from your Telegram client send:
    /help
    2+2?
    /reset

Check replies arrive. Ctrl-C to exit. Not run in CI.
"""
from __future__ import annotations

import sys

from bot import main

if __name__ == "__main__":
    sys.exit(main())
