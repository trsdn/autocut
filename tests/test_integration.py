"""End-to-end smoke test through the real ffmpeg binary.

Everything except ASR is exercised for real: WAV extraction, `silencedetect`
parsing, duration probing and cut-plan construction. ASR is bypassed with
``--transcript`` (a supplied word-timings file) and rendering with ``--dry-run``,
so the test stays fast and needs no models.

Skipped when ffmpeg/ffprobe are missing locally — but failed on CI, where the
workflow installs them and their absence means the workflow is broken rather
than the machine being unequipped.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from conftest import unavailable

from autocut.cli import main

DURATION = 6.0
SILENCE_START, SILENCE_END = 2.0, 4.0


@pytest.fixture(scope="module", autouse=True)
def require_ffmpeg():
    """Gate the module without letting a missing binary pass for a green run."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        unavailable(
            "ffmpeg/ffprobe not installed, so the end-to-end pipeline was never run",
            ci_remedy=(
                "the `test` job in .github/workflows/ci.yml must keep its "
                "`Install ffmpeg` step — without it this whole module sits out "
                "and CI still reports success."
            ),
        )


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """A 6 s clip whose audio is muted between t=2 s and t=4 s."""
    path = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={DURATION}",
            "-f", "lavfi", "-i",
            f"sine=frequency=440:duration={DURATION},"
            f"volume=volume=0:enable='between(t,{SILENCE_START},{SILENCE_END})'",
            "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def project(tmp_path, clip):
    """A project root with the clip in input/ and a hand-written transcript."""
    (tmp_path / "input").mkdir()
    shutil.copy(clip, tmp_path / "input" / "clip.mp4")

    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "wordTimings": [
                    {"word": "Hello", "startTime": 0.2, "endTime": 0.6},
                    {"word": "um", "startTime": 0.8, "endTime": 1.0},
                    {"word": "world.", "startTime": 1.1, "endTime": 1.6},
                    {"word": "Goodbye.", "startTime": 4.5, "endTime": 5.2},
                ]
            }
        )
    )
    return tmp_path, transcript


def run_autocut(root, transcript, *extra) -> tuple[int, dict]:
    code = main(
        ["--root", str(root), "--transcript", str(transcript), "--dry-run", *extra]
    )
    plan_path = root / "output" / "clip" / ".work" / "cut_plan.json"
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else {}
    return code, plan


def test_the_pipeline_completes_and_writes_a_cut_plan(project):
    root, transcript = project

    code, plan = run_autocut(root, transcript)

    assert code == 0
    assert plan["source"].endswith("clip.mp4")
    assert plan["duration"] == pytest.approx(DURATION, abs=0.2)


def test_a_16k_mono_wav_is_extracted_for_analysis(project):
    root, transcript = project

    run_autocut(root, transcript)

    wav = root / "output" / "clip" / ".work" / "audio_16k.wav"
    assert wav.exists() and wav.stat().st_size > 0
    rate, channels = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-of", "default=nw=1:nk=1", str(wav)],
        text=True,
    ).split()
    assert (rate, channels) == ("16000", "1")


def test_the_muted_stretch_is_detected_and_trimmed(project):
    """ffmpeg really finds the 2 s of silence, and the plan really cuts it."""
    root, transcript = project

    _, plan = run_autocut(root, transcript)

    pauses = [r for r in plan["removed"] if "pause" in r["kind"]]
    assert pauses, "the muted 2 s stretch should have produced a pause removal"
    trimmed = max(pauses, key=lambda r: r["end"] - r["start"])
    assert trimmed["start"] >= SILENCE_START - 0.3
    assert trimmed["end"] <= SILENCE_END + 0.3
    assert trimmed["end"] - trimmed["start"] > 1.0


def test_the_filler_word_from_the_transcript_is_removed(project):
    root, transcript = project

    _, plan = run_autocut(root, transcript)

    fillers = [r for r in plan["removed"] if "filler" in r["kind"]]
    assert [r["note"] for r in fillers] == ["um"]


def test_no_fillers_leaves_the_filler_in_place(project):
    root, transcript = project

    _, plan = run_autocut(root, transcript, "--no-fillers")

    assert not [r for r in plan["removed"] if "filler" in r["kind"]]


def test_protecting_a_range_suppresses_filler_cuts(project):
    root, transcript = project

    _, plan = run_autocut(root, transcript, "--protect", "0:6")

    assert not [r for r in plan["removed"] if "filler" in r["kind"]]


def test_pauses_inside_a_protected_range_are_trimmed_more_gently(project):
    """Protection does not freeze a block; it switches to the generous keep."""
    root, transcript = project

    _, unprotected = run_autocut(root, transcript)
    _, protected = run_autocut(root, transcript, "--protect", "0:6")

    assert all("(protected)" in r["note"] for r in protected["removed"])
    unprotected_pause = max(
        (r["end"] - r["start"] for r in unprotected["removed"] if "pause" in r["kind"]),
        default=0.0,
    )
    protected_pause = max(
        (r["end"] - r["start"] for r in protected["removed"] if "pause" in r["kind"]),
        default=0.0,
    )
    assert 0.0 < protected_pause < unprotected_pause


def test_the_plan_never_removes_more_than_the_clip_contains(project):
    root, transcript = project

    _, plan = run_autocut(root, transcript)

    kept = sum(e - s for s, e in plan["keep"])
    removed = sum(r["end"] - r["start"] for r in plan["removed"])
    assert kept + removed == pytest.approx(plan["duration"], abs=0.05)


def test_dry_run_does_not_write_an_output_video(project):
    root, transcript = project

    run_autocut(root, transcript)

    assert not (root / "output" / "clip" / "clip_cut.mp4").exists()
