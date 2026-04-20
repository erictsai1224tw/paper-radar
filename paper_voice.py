"""Text-to-speech via edge-tts for daily paper voice overview."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_VOICE = "zh-TW-HsiaoYuNeural"  # Taiwan Mandarin, female


async def _synth_async(text: str, out_path: Path, voice: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def generate_audio(
    text: str, out_path: Path | str, voice: str = _DEFAULT_VOICE
) -> Path | None:
    """Synthesize ``text`` to MP3 via Microsoft Edge's TTS.

    Returns the output path on success, ``None`` on any failure (callers should
    not let TTS failures abort the pipeline).
    """
    if not text.strip():
        logger.info("voice: empty text — skipping synthesis")
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(_synth_async(text, out_path, voice))
    except Exception as exc:
        logger.warning("edge-tts synthesis failed: %s", exc)
        return None
    if not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning("edge-tts produced empty file at %s", out_path)
        return None
    return out_path
