"""Silence detection: ffmpeg stderr parsing and timestamp snapping."""
from __future__ import annotations

import subprocess
from pathlib import Path

from autocut.silence import detect_silences, snap


class _FakeCompleted:
    def __init__(self, stderr: str):
        self.stderr = stderr
        self.returncode = 0


def _fake_ffmpeg(monkeypatch, stderr: str) -> list[list[str]]:
    """Replace subprocess.run in autocut.silence, recording the commands issued."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


SILENCEDETECT_STDERR = """\
[silencedetect @ 0x600] silence_start: 1.5
[silencedetect @ 0x600] silence_end: 2.25 | silence_duration: 0.75
[silencedetect @ 0x600] silence_start: 10.125
[silencedetect @ 0x600] silence_end: 11 | silence_duration: 0.875
"""


def test_detect_silences_parses_start_end_pairs(monkeypatch):
    _fake_ffmpeg(monkeypatch, SILENCEDETECT_STDERR)

    assert detect_silences(Path("a.wav"), "ffmpeg") == [(1.5, 2.25), (10.125, 11.0)]


def test_detect_silences_ignores_unterminated_trailing_start(monkeypatch):
    """A silence that never ends (file ends mid-silence) yields no pair."""
    stderr = "silence_start: 4.0\n"
    _fake_ffmpeg(monkeypatch, stderr)

    assert detect_silences(Path("a.wav"), "ffmpeg") == []


def test_detect_silences_ignores_end_without_start(monkeypatch):
    _fake_ffmpeg(monkeypatch, "silence_end: 9.5 | silence_duration: 1.0\n")

    assert detect_silences(Path("a.wav"), "ffmpeg") == []


def test_detect_silences_passes_threshold_and_duration_to_ffmpeg(monkeypatch):
    calls = _fake_ffmpeg(monkeypatch, "")

    detect_silences(Path("clip.wav"), "/usr/bin/ffmpeg", noise_db=-40.0, min_dur=0.15)

    cmd = calls[0]
    assert cmd[0] == "/usr/bin/ffmpeg"
    assert "silencedetect=noise=-40.0dB:d=0.15" in cmd
    assert "clip.wav" in cmd
    # Analysis only: decode to the null muxer, never write a file.
    assert cmd[-3:] == ["-f", "null", "-"]


def test_snap_returns_input_when_no_boundary_in_window():
    assert snap(5.0, [(0.0, 0.5)], window=0.3) == 5.0


def test_snap_moves_to_nearest_silence_start():
    # 1.05 is 0.05 from the silence start at 1.0.
    assert snap(1.05, [(1.0, 2.0)], window=0.3) == 1.0


def test_snap_moves_to_nearest_silence_end():
    assert snap(1.95, [(1.0, 2.0)], window=0.3) == 2.0


def test_snap_can_target_the_silence_midpoint():
    """The midpoint is a valid cut point: it leaves silence on both sides."""
    assert snap(1.45, [(1.0, 2.0)], window=0.3) == 1.5


def test_snap_window_is_exclusive_at_the_boundary():
    # Exactly `window` away is not closer than `window`, so nothing snaps.
    assert snap(1.5, [(1.0, 1.0)], window=0.5) == 1.5
    assert snap(1.4, [(1.0, 1.0)], window=0.5) == 1.0


def test_snap_picks_the_closest_of_several_silences():
    assert snap(4.02, [(1.0, 2.0), (4.0, 6.0), (9.0, 9.5)], window=0.3) == 4.0
