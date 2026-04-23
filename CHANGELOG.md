# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-23

### Added
- Initial release.
- `autocut` CLI with `talk` / `meeting` / `vlog` presets and granular overrides.
- Word-level ASR via three backends:
  - **FluidAudio** (macOS, CoreML Parakeet-TDT v3, ~150× realtime, auto-bootstrapped).
  - **NeMo Parakeet** (cross-platform via `pip install autocut[nemo]`; chunked 30 s inference; CUDA or CPU).
  - **whisper.cpp** (portable fallback).
- Silence detection (coarse −35 dB / 250 ms + fine −40 dB / 150 ms) with snap-to-boundary.
- Cut-plan builder: filler removal (DE/EN), narrator-pause trim, protected-range pause trim, redundancy ranges.
- Optional semantic redundancy detection via any OpenAI-compatible `/v1/chat/completions` endpoint (stdlib `urllib`, no `openai` SDK). Default model `gpt-5.4-mini`, 16384 output tokens.
- Configurable audio chain: highpass → acompressor → de-ess → loudnorm (EBU R128).
- `input/` and `output/` working folders with per-folder `.gitignore`.
- Caching: WAV, transcript, and cut plan persisted under `output/<stem>/.work/` for fast re-runs.
- Zero Python runtime dependencies (stdlib only).

[0.1.0]: https://github.com/trsdn/autocut/releases/tag/v0.1.0
