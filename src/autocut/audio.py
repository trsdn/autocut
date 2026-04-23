"""Audio extraction helpers."""
from __future__ import annotations
import subprocess
from pathlib import Path


def extract_wav_16k_mono(ffmpeg: str, src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(dst),
    ])
    return dst


def probe_duration(ffprobe: str, src: Path) -> float:
    out = subprocess.check_output([
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(src),
    ], text=True).strip()
    return float(out)
