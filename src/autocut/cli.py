"""autocut — CLI entry point.

Pipeline:
  1. Extract 16 kHz mono WAV
  2. Transcribe (FluidAudio / whisper.cpp) → word timings
  3. Detect silences (coarse + fine)
  4. Optional: LLM redundancy detection
  5. Build cut plan
  6. Render with speed + clean audio chain

Presets:
  --preset talk   : default — lecture/demo/narration
  --preset meeting: keep more pauses, no filler cuts (preserves turn-taking)
  --preset vlog   : aggressive filler + pause trimming, slight speedup
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .audio import extract_wav_16k_mono, probe_duration
from .deps import check_ffmpeg, DependencyError
from .llm import LLMConfig, find_redundancies
from .plan import build_plan
from .render import render
from .silence import detect_silences
from .transcribe import transcribe


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
PRESETS: dict[str, dict] = {
    "talk": dict(
        speed=1.0, cut_fillers=True,
        pause_narrator_above=0.35, pause_narrator_keep=0.20,
        pause_protected_above=0.60, pause_protected_keep=0.30,
    ),
    "meeting": dict(
        speed=1.0, cut_fillers=False,
        pause_narrator_above=0.80, pause_narrator_keep=0.50,
        pause_protected_above=1.20, pause_protected_keep=0.80,
    ),
    "vlog": dict(
        speed=1.05, cut_fillers=True,
        pause_narrator_above=0.25, pause_narrator_keep=0.12,
        pause_protected_above=0.50, pause_protected_keep=0.25,
    ),
}


def parse_range(s: str) -> tuple[float, float]:
    a, b = s.split(":")
    return float(a), float(b)


VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}


def resolve_input(value: Path | None, root: Path) -> Path:
    """Resolve the input video.

    - If `value` exists as given, use it.
    - Else try `<root>/input/<value>` (allows bare filenames).
    - If `value` is None, pick the newest video in `<root>/input/`.
    """
    in_dir = root / "input"
    if value is not None:
        if value.exists():
            return value
        cand = in_dir / value
        if cand.exists():
            return cand
        raise FileNotFoundError(f"Input not found: {value} (also tried {cand})")

    if not in_dir.is_dir():
        raise FileNotFoundError(
            f"No input given and {in_dir} does not exist. "
            "Create it and drop a video in, or pass a path."
        )
    vids = [p for p in in_dir.iterdir() if p.suffix.lower() in VIDEO_EXT]
    if not vids:
        raise FileNotFoundError(f"No video files in {in_dir}")
    return max(vids, key=lambda p: p.stat().st_mtime)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autocut",
        description="Automated video re-cut: transcribe, detect pauses/fillers, render.",
    )
    p.add_argument("input", type=Path, nargs="?",
                   help="Input video (path, or bare filename inside ./input/). "
                        "If omitted, picks newest video from ./input/.")
    p.add_argument("-o", "--output", type=Path,
                   help="Output file (default: ./output/<stem>/<stem>_cut.mp4)")
    p.add_argument("--root", type=Path, default=Path.cwd(),
                   help="Project root containing input/ and output/ (default: cwd)")
    p.add_argument("--preset", choices=list(PRESETS), default="talk")
    p.add_argument("--version", action="version",
                   version=f"autocut {__version__}")

    # Speed / fades / codecs
    g = p.add_argument_group("video/audio knobs")
    g.add_argument("--speed", type=float,
                   help="Playback speed (overrides preset)")
    g.add_argument("--fade-ms", type=int, default=40,
                   help="Per-segment audio fade in ms (default 40)")
    g.add_argument("--crf", type=int, default=20)
    g.add_argument("--preset-enc", default="medium",
                   help="x264 preset (ultrafast..veryslow)")
    g.add_argument("--loudnorm-i",  type=float, default=-16.0)
    g.add_argument("--loudnorm-tp", type=float, default=-1.5)
    g.add_argument("--compressor-ratio", type=float, default=2.5)
    g.add_argument("--deess-db", type=float, default=-2.5)
    g.add_argument("--highpass-hz", type=int, default=80)

    # Cut behaviour
    g = p.add_argument_group("cut logic")
    g.add_argument("--protect", action="append", type=parse_range, default=[],
                   metavar="START:END",
                   help="Range in seconds to preserve (repeatable)")
    g.add_argument("--no-fillers", action="store_true",
                   help="Do not remove filler words (um/uh/äh)")
    g.add_argument("--language", default="en", choices=["en", "de"])
    g.add_argument("--pause-above",  type=float, help="Override narrator pause threshold (s)")
    g.add_argument("--pause-keep",   type=float, help="Override narrator pause kept duration (s)")
    g.add_argument("--silence-db",   type=float, default=-35.0)
    g.add_argument("--silence-db-fine", type=float, default=-40.0)

    # ASR
    g = p.add_argument_group("transcription")
    g.add_argument("--asr-backend", choices=["fluidaudio", "nemo", "whisper-cpp"],
                   default="fluidaudio",
                   help="fluidaudio: macOS CoreML (fast, built-in). "
                        "nemo: cross-platform Parakeet via NeMo+PyTorch "
                        "(install with `pip install autocut[nemo]`). "
                        "whisper-cpp: portable fallback.")
    g.add_argument("--whisper-model",
                   help="Path to ggml-*.bin (required for whisper-cpp)")
    g.add_argument("--nemo-model",
                   help="HF model id for nemo backend "
                        "(default: nvidia/parakeet-tdt-0.6b-v3)")
    g.add_argument("--transcript", type=Path,
                   help="Reuse existing word-timings JSON")

    # LLM
    g = p.add_argument_group("LLM redundancy detection (optional)")
    g.add_argument("--llm", action="store_true",
                   help="Enable LLM-based redundancy detection")
    g.add_argument("--llm-base-url")
    g.add_argument("--llm-api-key")
    g.add_argument("--llm-model",
                   help="Chat model id (default: gpt-5.4-mini)")
    g.add_argument("--llm-max-tokens", type=int,
                   help="Max output tokens for the LLM (default: 16384)")
    g.add_argument("--llm-temperature", type=float,
                   help="Sampling temperature (default: 0.1)")

    # Plumbing
    g = p.add_argument_group("plumbing")
    g.add_argument("--workdir", type=Path,
                   help="Directory for intermediate files (default: <output-dir>/.work)")
    g.add_argument("--keep-intermediates", action="store_true")
    g.add_argument("--dry-run", action="store_true",
                   help="Build plan and print, but do not render")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        src = resolve_input(args.input, args.root)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr); return 2
    print(f"→ input:  {src}")

    try:
        ffmpeg, ffprobe = check_ffmpeg()
    except DependencyError as e:
        print(f"error: {e}", file=sys.stderr); return 2

    preset = PRESETS[args.preset].copy()
    if args.speed is not None:           preset["speed"] = args.speed
    if args.no_fillers:                  preset["cut_fillers"] = False
    if args.pause_above is not None:     preset["pause_narrator_above"] = args.pause_above
    if args.pause_keep  is not None:     preset["pause_narrator_keep"]  = args.pause_keep

    out_dir = (args.root / "output" / src.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = args.output or out_dir / f"{src.stem}_cut.mp4"
    workdir = args.workdir or out_dir / ".work"
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"→ output: {out}")

    wav = workdir / "audio_16k.wav"
    if not wav.exists():
        print(f"→ extract wav: {wav}")
        extract_wav_16k_mono(ffmpeg, src, wav)

    tx_json = args.transcript or workdir / "transcript.json"
    if not tx_json.exists():
        doc = transcribe(wav, tx_json,
                         backend=args.asr_backend,
                         whisper_model=args.whisper_model,
                         nemo_model=args.nemo_model)
    else:
        print(f"→ reuse transcript: {tx_json}")
        doc = json.load(open(tx_json))

    words = doc.get("wordTimings") or doc.get("words") or []
    if not words:
        print("error: transcript has no word timings", file=sys.stderr); return 3

    # Silences are detected on the original timeline, but cut plan must be in
    # the post-speed timeline. We scale silence timestamps by 1/speed below.
    speed = preset["speed"]
    print(f"→ detect silences ({args.silence_db} dB / {args.silence_db_fine} dB)")
    sil_c = detect_silences(wav, ffmpeg, noise_db=args.silence_db,       min_dur=0.25)
    sil_f = detect_silences(wav, ffmpeg, noise_db=args.silence_db_fine,  min_dur=0.15)

    # FluidAudio/whisper word timings are on the ORIGINAL audio (same as wav).
    # Cut plan is expressed on post-speed timeline — rescale all timestamps.
    inv = 1.0 / speed
    words_sp = [{**w,
                 "startTime": w["startTime"] * inv,
                 "endTime":   w["endTime"]   * inv} for w in words]
    sil_c_sp = [(s*inv, e*inv) for s, e in sil_c]
    sil_f_sp = [(s*inv, e*inv) for s, e in sil_f]
    protect_sp = [(s, e) for s, e in args.protect]  # user gives post-speed already
    src_duration = probe_duration(ffprobe, src) * inv

    # Optional LLM redundancy pass
    redundancies: list[tuple[float, float, str]] = []
    if args.llm:
        cfg = LLMConfig.load({
            "base_url":    args.llm_base_url,
            "api_key":     args.llm_api_key,
            "model":       args.llm_model,
            "max_tokens":  args.llm_max_tokens,
            "temperature": args.llm_temperature,
        })
        redundancies = find_redundancies(
            words_sp, cfg=cfg, protect_ranges=protect_sp,
        )

    plan = build_plan(
        source=str(src),
        duration=src_duration,
        words=words_sp,
        silences_coarse=sil_c_sp,
        silences_fine=sil_f_sp,
        language=args.language,
        redundancy_ranges=redundancies,
        protect_ranges=protect_sp,
        pause_trim_narrator_above=preset["pause_narrator_above"],
        pause_trim_narrator_keep=preset["pause_narrator_keep"],
        pause_trim_protected_above=preset["pause_protected_above"],
        pause_trim_protected_keep=preset["pause_protected_keep"],
        cut_fillers=preset["cut_fillers"],
    )
    plan_path = workdir / "cut_plan.json"
    plan.write(plan_path)

    kept = sum(e - s for s, e in plan.keep)
    print(f"→ plan: removed {plan.total_removed():.1f}s, kept {kept:.1f}s "
          f"({len(plan.keep)} segments) → {plan_path}")

    if args.dry_run:
        return 0

    out_dur = render(
        ffmpeg=ffmpeg,
        src=src,
        dst=out,
        keep=plan.keep,
        speed=speed,
        fade=args.fade_ms / 1000.0,
        highpass_hz=args.highpass_hz,
        compressor_ratio=args.compressor_ratio,
        deess_db=args.deess_db,
        loudnorm_i=args.loudnorm_i,
        loudnorm_tp=args.loudnorm_tp,
        crf=args.crf,
        preset=args.preset_enc,
    )
    print(f"✓ {out}  ({out_dur:.1f}s)")

    if not args.keep_intermediates:
        pass  # leave them; useful for iteration
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
