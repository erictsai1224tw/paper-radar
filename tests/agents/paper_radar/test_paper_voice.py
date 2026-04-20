"""Tests for paper_voice. We mock the internal async synth so edge-tts never
calls the Microsoft endpoint during tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from paper_voice import generate_audio


def _fake_synth_writes(bytes_to_write: bytes):
    async def _impl(text, out_path, voice):
        Path(out_path).write_bytes(bytes_to_write)
    return _impl


def test_generate_audio_writes_mp3_on_success(tmp_path: Path):
    out = tmp_path / "out.mp3"
    with patch("paper_voice._synth_async", side_effect=_fake_synth_writes(b"\xff\xfb\x90\x00 mp3")):
        result = generate_audio("你好", out)
    assert result == out
    assert out.stat().st_size > 0


def test_generate_audio_returns_none_on_empty_text(tmp_path: Path):
    out = tmp_path / "out.mp3"
    assert generate_audio("", out) is None
    assert generate_audio("   ", out) is None
    assert not out.exists()


def test_generate_audio_returns_none_on_synth_error(tmp_path: Path):
    out = tmp_path / "out.mp3"

    async def boom(text, out_path, voice):
        raise RuntimeError("synth error")

    with patch("paper_voice._synth_async", side_effect=boom):
        assert generate_audio("some text", out) is None


def test_generate_audio_returns_none_when_output_is_empty(tmp_path: Path):
    out = tmp_path / "out.mp3"
    with patch("paper_voice._synth_async", side_effect=_fake_synth_writes(b"")):
        assert generate_audio("some text", out) is None


def test_generate_audio_creates_parent_dir(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "out.mp3"
    with patch("paper_voice._synth_async", side_effect=_fake_synth_writes(b"\xff\xfb")):
        result = generate_audio("hi", nested)
    assert result == nested
    assert nested.exists()
