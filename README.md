# autocut

[![PyPI](https://img.shields.io/pypi/v/trsdn-autocut?label=pypi%20trsdn-autocut)](https://pypi.org/project/trsdn-autocut/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](#platform-notes)
[![Release](https://img.shields.io/github/v/release/trsdn/autocut?display_name=tag&sort=semver)](https://github.com/trsdn/autocut/releases)
[![Changelog](https://img.shields.io/badge/changelog-keep%20a%20changelog-orange)](CHANGELOG.md)

> **Cut the waffle. Keep the signal.**
> Drop a talk, demo or screen recording in — get a tighter, louder-sounding edit out. One command.

`autocut` transcribes your video with word-level timestamps, kills silence,
fillers and restated sentences, optionally lets an LLM flag redundant
passages, and renders a clean result with a broadcast-standard audio chain
(EBU R128, −16 LUFS). **No Premiere. No DaVinci. No manual scrubbing.**

```bash
autocut talk.mp4 --speed 1.25 --protect 303:415 --llm
# → output/talk/talk_cut.mp4 · 12:14 → 6:27 · clean audio · usable immediately
```

---

## Why autocut

Typical screen recordings are 30–50 % pauses, "ums", and restatements.
Manual editing is tedious; AI "magic editors" are opaque black boxes.

`autocut` is the opposite:

- **Deterministic** — every cut is in `cut_plan.json`, you can inspect it.
- **Honest defaults** — the `talk` preset is tuned on real lecture recordings;
  nothing touches your video until you like the plan (`--dry-run`).
- **Local-first** — Parakeet ASR runs on your machine (CoreML on macOS,
  CUDA/CPU elsewhere). An LLM pass is **optional** and works with any
  OpenAI-compatible endpoint, including Ollama, LM Studio, or your own gateway.
- **Zero lock-in** — MIT, zero Python runtime deps. `pip install trsdn-autocut` and go.

## Use cases

| Workflow                       | What autocut does for you                                                           |
|--------------------------------|-------------------------------------------------------------------------------------|
| Conference talks / lectures    | Trims dead air, fillers, restarts → 20–40 % shorter, more watchable.                |
| Internal demos & screencasts   | Speeds up 1.25×, normalizes loudness across recordings.                             |
| Podcast raw cuts               | Builds a first editable cut from raw takes — editors start from 80 %, not 0.        |
| Customer calls → shareable clips | Protect a key range (`--protect 303:415`), tighten everything else.               |
| Course creators                | Reproducible pipeline — same settings → same style across dozens of videos.         |

---

## Install

```bash
pip install trsdn-autocut       # or: uv tool install trsdn-autocut
autocut --help

# no install at all:
uvx --from trsdn-autocut autocut talk.mp4
```

> **Why two names?** The PyPI distribution name is **`trsdn-autocut`** because
> the plain `autocut` name on PyPI belongs to an unrelated project. The command
> you run and the Python import package are still **`autocut`** — only the
> `pip install` name differs.

From source:

```bash
git clone https://github.com/trsdn/autocut.git
cd autocut
pip install -e .       # or: uv pip install -e .
```

That's it on macOS once `ffmpeg` is installed (`brew install ffmpeg`).
The FluidAudio Parakeet CLI auto-builds on first run.

### External dependencies

| Tool                 | Purpose                              | Install                                          |
|----------------------|--------------------------------------|--------------------------------------------------|
| `ffmpeg` / `ffprobe` | required — audio/video pipeline      | `brew install ffmpeg` · `apt install ffmpeg`     |
| FluidAudio CLI       | ASR, macOS (CoreML), ~150× realtime  | auto-built into `~/.cache/autocut/` on first run |
| NeMo Parakeet        | ASR, Windows / Linux / macOS         | `pip install 'trsdn-autocut[nemo]'`              |
| `whisper.cpp`        | ASR, portable minimal-deps fallback  | `brew install whisper-cpp`                       |

Parakeet-TDT v3 is the same multilingual model across all three backends.

---

## Quick start

Drop a video into `input/` and run:

```bash
autocut                       # picks newest video from ./input/
autocut my_video.mp4          # bare filename resolves against ./input/
autocut /abs/path/clip.mov    # absolute paths work too
```

Output lands under `output/<stem>/<stem>_cut.mp4`. Intermediates are cached
in `output/<stem>/.work/` so repeat runs (different settings, same source)
skip re-transcription:

```
output/talk/
├── talk_cut.mp4
└── .work/
    ├── audio_16k.wav
    ├── transcript.json      ← word-level timings
    └── cut_plan.json        ← every kept/removed range, inspectable
```

### Common recipes

```bash
# Preserve a negotiation block exactly, speed up the rest
autocut talk.mp4 --speed 1.25 --protect 303:415

# Preview the plan without rendering
autocut talk.mp4 --dry-run

# Use an LLM to flag restated sentences (optional, any OpenAI-compatible API)
export AUTOCUT_LLM_API_KEY=sk-...
autocut talk.mp4 --llm

# Meeting preset: keep turn-taking pauses, don't touch fillers
autocut kickoff.mp4 --preset meeting

# Cross-platform (Windows / Linux)
pip install 'trsdn-autocut[nemo]'
autocut talk.mp4 --asr-backend nemo
```

---

## How it works

```
 source.mp4
     │
     ▼
 ┌────────────────────┐      ┌──────────────────────────┐
 │ 1. extract 16k wav │ ───▶ │ 2. ASR (word timestamps) │
 └────────────────────┘      │  FluidAudio / NeMo /      │
                             │  whisper.cpp              │
                             └────────────┬──────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
     ┌────────────────┐         ┌──────────────────┐         ┌────────────────┐
     │ 3. silences    │         │ 4. filler regex  │         │ 5. LLM pass    │
     │ −35 / −40 dB   │         │ um / äh / ähm    │         │ (optional)     │
     └───────┬────────┘         └─────────┬────────┘         └───────┬────────┘
             └──────────────┬─────────────┴──────────────────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ 6. cut_plan.json     │  ← every cut is auditable
                 │    keep + remove     │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────────┐
                 │ 7. ffmpeg render         │
                 │    split/trim/atrim ·    │
                 │    40 ms fades · speed · │
                 │    highpass · comp ·     │
                 │    de-ess · loudnorm     │
                 └──────────┬───────────────┘
                            ▼
                      output.mp4
```

Every step is a small, independent module. Swap the ASR, tweak the audio
chain, bring your own cut plan.

---

## Presets

| Preset    | Speed | Fillers | Narrator pauses       | Protected pauses      | Good for                     |
|-----------|-------|---------|-----------------------|-----------------------|------------------------------|
| `talk`    | 1.00× | cut     | trim >0.35 s → 0.20 s | trim >0.60 s → 0.30 s | lectures, demos, tutorials   |
| `meeting` | 1.00× | keep    | trim >0.80 s → 0.50 s | trim >1.20 s → 0.80 s | interviews, panels, calls    |
| `vlog`    | 1.05× | cut     | trim >0.25 s → 0.12 s | trim >0.50 s → 0.25 s | punchy solo-to-camera videos |

Every preset knob is also exposed as a flag — override any single value
without abandoning the preset.

## Audio chain (`talk` preset)

| Stage           | Parameter                                                         |
|-----------------|-------------------------------------------------------------------|
| High-pass       | 80 Hz                                                             |
| Compressor      | thresh −22 dB · ratio 2.5 · atk 10 / rel 200 ms · makeup 2        |
| De-ess          | 6500 Hz · −2.5 dB · Q=3                                           |
| Loudness norm.  | EBU R128 · I = −16 LUFS · TP = −1.5 dBTP · LRA = 11               |
| Per-segment     | 40 ms triangular fades (no clicks on cuts)                        |

Values come from iterating on real bilingual screen recordings — not from a
textbook. Tweak freely via flags.

---

## LLM config (optional)

The LLM pass flags **semantic** cuts — restated sentences, aborted restarts,
redundant examples — that regex can't catch. Config precedence:

1. CLI flags: `--llm-base-url`, `--llm-api-key`, `--llm-model`, `--llm-max-tokens`, `--llm-temperature`
2. Env vars: `AUTOCUT_LLM_BASE_URL`, `AUTOCUT_LLM_API_KEY`, `AUTOCUT_LLM_MODEL`, `AUTOCUT_LLM_MAX_TOKENS`, `AUTOCUT_LLM_TEMPERATURE`
3. Config file: `~/.config/autocut/config.json` (see [`config.example.json`](config.example.json))

Works with anything that speaks `/v1/chat/completions`:
**OpenAI · Azure OpenAI · Ollama · LM Studio · together.ai · Groq · your own gateway.**

Default: `gpt-5.4-mini`, 16 384 output tokens, temperature 0.1.

---

## CLI reference

```
autocut [INPUT] [-o OUTPUT] [--root DIR]
        [--preset talk|meeting|vlog]
        [--speed FLOAT] [--fade-ms INT]
        [--protect START:END ...] [--no-fillers] [--language en|de]
        [--pause-above SEC] [--pause-keep SEC]
        [--silence-db DB] [--silence-db-fine DB]
        [--asr-backend fluidaudio|nemo|whisper-cpp]
        [--whisper-model PATH] [--nemo-model HF_ID] [--transcript JSON]
        [--llm] [--llm-base-url URL] [--llm-api-key KEY]
        [--llm-model NAME] [--llm-max-tokens INT] [--llm-temperature FLOAT]
        [--crf INT] [--preset-enc NAME]
        [--loudnorm-i LUFS] [--loudnorm-tp DB]
        [--compressor-ratio FLOAT] [--deess-db DB] [--highpass-hz HZ]
        [--workdir DIR] [--keep-intermediates] [--dry-run]
```

Run `autocut --help` for the full list with descriptions.

---

## Platform notes

- **macOS** *(recommended)* — FluidAudio Parakeet-TDT runs on CoreML at
  ~150× realtime. First run builds the CLI (~1 min) and downloads the model
  (~600 MB).
- **Windows / Linux** — `pip install 'trsdn-autocut[nemo]'`, then
  `--asr-backend nemo`. Parakeet-TDT v3 via NeMo with chunked (30 s)
  inference; uses CUDA if available, falls back to CPU. First run downloads
  the model (~2.5 GB).
- **Minimal-deps fallback (any OS)** —
  `--asr-backend whisper-cpp --whisper-model /path/to/ggml-large-v3.bin`.

---

## Project layout

```
src/autocut/
├── cli.py           # argparse entry point, presets, orchestration
├── audio.py         # wav extraction / probe helpers
├── deps.py          # external tool detection + FluidAudio bootstrap
├── transcribe.py    # ASR backend dispatcher
├── nemo_backend.py  # cross-platform Parakeet via NeMo (optional extra)
├── silence.py       # silencedetect parsing + snap-to-boundary
├── plan.py          # cut plan: fillers, pauses, redundancies
├── render.py        # ffmpeg filter_complex render
└── llm.py           # OpenAI-compatible redundancy detection (stdlib urllib)
```

Every module is under 200 lines. Read it. Fork it. Make it yours.

## Contributing

Issues and PRs welcome. This started as a tool to shorten a 12-minute
negotiation demo; it generalised from there. If you hit an edge case —
unusual language, weird microphone, exotic codec — open an issue with the
source clip (or a redacted transcript) and I'll take a look.

### Releasing

Releases are published to PyPI automatically by
[`.github/workflows/release.yml`](.github/workflows/release.yml) using
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — GitHub Actions
OIDC, no API tokens or repository secrets.

1. Bump `version` in `pyproject.toml` and add a `CHANGELOG.md` entry.
2. Commit to `main`.
3. Tag and push:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

The workflow builds sdist + wheel, gates on `twine check --strict`, and
publishes from the `pypi` environment. `__version__` is read from the installed
package metadata, so it follows `pyproject.toml` automatically.

Tag and `version` must match, and a version can only ever be uploaded to PyPI
once — bump again rather than trying to replace a published release.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [FluidAudio](https://github.com/FluidInference/FluidAudio) — CoreML Swift ASR runner
- [NVIDIA Parakeet-TDT](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) — the excellent multilingual ASR model
- [NeMo toolkit](https://github.com/NVIDIA/NeMo) — cross-platform inference
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — portable fallback
- [FFmpeg](https://ffmpeg.org/) — without which none of this would exist
