# autocut

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](#platform-notes)
[![Release](https://img.shields.io/github/v/release/trsdn/autocut?display_name=tag&sort=semver)](https://github.com/trsdn/autocut/releases)
[![Changelog](https://img.shields.io/badge/changelog-keep%20a%20changelog-orange)](CHANGELOG.md)

Automated video re-cut: transcribes with word-level timestamps, detects
silences and fillers, optionally asks an LLM for redundancy cuts, and renders
the result with a clean, broadcast-style audio chain.

Zero Python runtime dependencies — just stdlib + external binaries.

## Install

```bash
pip install -e .
# or with uv:
uv pip install -e .
```

### External dependencies

| Tool             | Purpose                        | Install                                           |
|------------------|--------------------------------|---------------------------------------------------|
| `ffmpeg`/`ffprobe` | required, audio/video pipeline | `brew install ffmpeg`                            |
| FluidAudio CLI   | ASR, macOS only (CoreML), fastest | auto-cloned+built into `~/.cache/autocut/` on first use (needs `swift`, `git`) |
| NeMo Parakeet    | ASR, cross-platform (Win/Linux/macOS) | `pip install 'autocut[nemo]'` — pulls torch + nemo_toolkit |
| `whisper.cpp`    | ASR, portable, tiny dep        | `brew install whisper-cpp` or build from source  |

Parakeet-TDT v3 is the recommended model on every OS. Pick the backend that
matches your platform:

- **macOS** → `--asr-backend fluidaudio` (default, ~150× realtime via CoreML)
- **Windows / Linux** → `pip install 'autocut[nemo]'` then `--asr-backend nemo`
  (chunked inference, 30 s windows, uses CUDA if available, else CPU)
- **Any** → `--asr-backend whisper-cpp` as a minimal-dep fallback

## Quick start

Drop a video into `input/` and run:

```bash
autocut                       # picks newest video from ./input/
autocut my_video.mp4          # bare filename → resolved against ./input/
autocut /abs/path/to/clip.mov # absolute path still works
```

Output lands under `output/<stem>/<stem>_cut.mp4`; intermediates
(`audio_16k.wav`, `transcript.json`, `cut_plan.json`) in `output/<stem>/.work/`
so repeat runs are cached and can be inspected.

```bash
# Preserve an important range, speed up the rest
autocut input.mp4 --speed 1.25 --protect 303:415

# With semantic redundancy detection (OpenAI-compatible endpoint)
export AUTOCUT_LLM_API_KEY=sk-...
autocut input.mp4 --llm --llm-model gpt-4o-mini
```

### Folder layout

```
<project>/
├── input/              # drop videos here (contents gitignored)
├── output/             # results + intermediates (contents gitignored)
│   └── <stem>/
│       ├── <stem>_cut.mp4
│       └── .work/
│           ├── audio_16k.wav
│           ├── transcript.json
│           └── cut_plan.json
```

Override the root with `--root <dir>`; override the output file with `-o`.

## LLM config

The LLM (OpenAI-compatible `/v1/chat/completions`) is **optional**. Config
sources, in precedence order:

1. CLI flags: `--llm-base-url`, `--llm-api-key`, `--llm-model`
2. Env vars: `AUTOCUT_LLM_BASE_URL`, `AUTOCUT_LLM_API_KEY`, `AUTOCUT_LLM_MODEL`
3. `~/.config/autocut/config.json` (see [`config.example.json`](config.example.json))

Works with any OpenAI-compatible endpoint: OpenAI, Azure OpenAI (via gateway),
Ollama (`/v1`), LM Studio, together.ai, Groq, etc.

## Presets

| Preset    | Speed | Fillers | Narrator pause trim | Protected pause trim |
|-----------|-------|---------|---------------------|----------------------|
| `talk`    | 1.00  | yes     | >0.35s → 0.20s      | >0.60s → 0.30s       |
| `meeting` | 1.00  | no      | >0.80s → 0.50s      | >1.20s → 0.80s       |
| `vlog`    | 1.05  | yes     | >0.25s → 0.12s      | >0.50s → 0.25s       |

## Pipeline stages

1. `extract_wav_16k_mono` → 16 kHz mono PCM
2. `transcribe` → word timings JSON (FluidAudio Parakeet-TDT v3 or whisper.cpp)
3. `detect_silences` → coarse (−35 dB / 250 ms) + fine (−40 dB / 150 ms)
4. Optional `find_redundancies` via LLM
5. `build_plan` → keep/remove ranges with silence snapping
6. `render` → ffmpeg `filter_complex` with `split`/`asplit`, per-segment
   `trim`/`atrim`, 40 ms triangular fades, concat, and audio chain:
   `highpass 80 → acompressor → de-ess → loudnorm -16 LUFS`

## Best-practice defaults (the `talk` preset)

These are the defaults that produced a clean result on a 12-minute bilingual
screen recording:

- Speed 1.25× (if passed explicitly)
- Fades: 40 ms triangular to avoid clicks
- Silence: −40 dB / 150 ms (fine) + −35 dB / 250 ms (coarse)
- Narrator pause trim: >0.35 s → 0.20 s
- Protected zone pause trim: >0.60 s → 0.30 s
- Fillers: `um`, `uh`, `uhm` / `äh`, `ähm` — with 60 ms padding, snapped to
  nearest silence ±120 ms
- Audio chain: highpass 80 Hz, acompressor −22 dB / 2.5:1 / 10 ms / 200 ms,
  de-ess 6500 Hz −2.5 dB (w=3), loudnorm I=−16 / TP=−1.5 / LRA=11
- Always render from the pristine source — never stack audio processing

## Commands / flags reference

```
autocut <input> [-o OUTPUT]
        [--preset talk|meeting|vlog]
        [--speed FLOAT] [--fade-ms INT]
        [--protect START:END ...] [--no-fillers] [--language en|de]
        [--pause-above SEC] [--pause-keep SEC]
        [--silence-db DB] [--silence-db-fine DB]
        [--asr-backend fluidaudio|whisper-cpp] [--whisper-model PATH]
        [--transcript JSON]
        [--llm] [--llm-base-url URL] [--llm-api-key KEY] [--llm-model NAME]
        [--crf INT] [--preset-enc NAME]
        [--loudnorm-i LUFS] [--loudnorm-tp DB]
        [--compressor-ratio FLOAT] [--deess-db DB] [--highpass-hz HZ]
        [--workdir DIR] [--keep-intermediates] [--dry-run]
```

## Platform notes

- **macOS (recommended)**: FluidAudio Parakeet-TDT runs on CoreML in ~150×
  realtime. First run builds the CLI (~1 min) and downloads the model
  (~600 MB).
- **Windows / Linux**: `pip install 'autocut[nemo]'` then
  `--asr-backend nemo`. Chunked (30 s) inference with Parakeet-TDT v3 via
  NeMo; uses CUDA if available, falls back to CPU. First run downloads the
  model (~2.5 GB) via HuggingFace.
- **Minimal-deps fallback (any OS)**: `--asr-backend whisper-cpp --whisper-model
  /path/to/ggml-large-v3.bin`.

## Layout

```
src/autocut/
├── __init__.py
├── cli.py         # argparse entry point, preset table, orchestration
├── audio.py       # wav extraction / probe helpers
├── deps.py        # external dep detection + FluidAudio bootstrap
├── transcribe.py  # ASR backends
├── silence.py     # silencedetect parsing + snapping
├── plan.py        # cut-plan builder (fillers, pauses, redundancies)
├── render.py      # ffmpeg filter_complex render
└── llm.py         # OpenAI-compatible redundancy detection (stdlib urllib)
```
