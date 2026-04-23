"""Silence detection via ffmpeg silencedetect."""
from __future__ import annotations
import re
import subprocess
from pathlib import Path


def detect_silences(audio_wav: Path, ffmpeg: str,
                    noise_db: float = -35.0,
                    min_dur: float = 0.25) -> list[tuple[float, float]]:
    """Return list of (start, end) silence intervals in seconds."""
    out = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(audio_wav),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
         "-f", "null", "-"],
        stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True,
    )
    pairs, cur = [], None
    for line in out.stderr.splitlines():
        m = re.search(r"silence_start:\s*([\d.]+)", line)
        if m: cur = float(m.group(1))
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and cur is not None:
            pairs.append((cur, float(m.group(1))))
            cur = None
    return pairs


def snap(t: float, silences: list[tuple[float, float]],
         window: float = 0.3) -> float:
    """Snap a timestamp to the nearest silence boundary (or center) within window."""
    best, best_d = t, window
    for s, e in silences:
        for cand in (s, e, (s + e) / 2):
            d = abs(cand - t)
            if d < best_d:
                best_d, best = d, cand
    return best
