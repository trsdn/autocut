# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Tag-triggered GitHub Releases.** `release.yml` now creates a GitHub Release
  for every version tag, with notes taken from the matching `CHANGELOG.md`
  section. The job holds the only `contents: write` in the workflow, scoped to
  itself, and runs after a successful publish so a release can never point at a
  version that is not on PyPI.
- **Release guards that run before anything is published.** A new `verify` job
  fails the run when the tag disagrees with `pyproject.toml`, or when the
  version has no changelog section or an empty one. PyPI version numbers can
  only be used once, so these checks deliberately run ahead of the upload
  rather than after it.
- `.github/scripts/release_notes.py` — extracts a single version's notes from
  `CHANGELOG.md`. Stdlib only, and outside `src/` so it never ships in the
  wheel. Covered by `tests/test_release_notes.py`, including the missing-section
  and empty-section failure paths and a check that every published git tag has
  notes.
- Continuous integration (`.github/workflows/ci.yml`): ruff, mypy and the test
  suite on Python 3.10–3.13 for every push and pull request, plus a packaging
  job that builds the sdist/wheel, gates on `twine check --strict`, and installs
  the built wheel into a clean virtualenv. CI never publishes anything —
  releasing stays entirely in `release.yml`.
- Test suite under `tests/` (pytest) covering the cut-plan builder,
  silence snapping and `silencedetect` parsing, LLM config precedence and
  response parsing, the whisper.cpp transcript normaliser, the ffmpeg filter
  graph, and external-tool discovery — plus an end-to-end test that drives the
  real ffmpeg binary and skips itself when ffmpeg is absent.
- Packaging guard tests that fail if `pyproject.toml`, `autocut.__version__` and
  `CHANGELOG.md` disagree, if a runtime dependency is ever added, if a module
  gains a third-party import at module level, or if the CI matrix stops matching
  the advertised Python classifiers.
- `AGENTS.md` documenting the verified build/test/lint commands, the pipeline
  architecture and the stdlib-only constraint.
- Dependabot (`.github/dependabot.yml`): weekly updates for GitHub Actions and
  for the `dev` / `nemo` optional dependency groups.
- Ruff, mypy and pytest configuration in `pyproject.toml`; `ruff` and `mypy`
  added to the `dev` extra.

### Fixed
- Removed two dead imports (`sys` in `deps.py`, `numpy` in `nemo_backend.py`).
- `CHANGELOG.md` had no entry for 0.2.3, which is tagged and published on PyPI.
- `.gitignore` only covered `.venv/`, so a differently named local virtualenv
  could be swept into the built sdist.

## [0.2.3] - 2026-08-24

### Added
- PyPI version badge in the README.
- README section documenting the release process (bump, changelog, tag, push)
  and the Trusted Publishing setup behind it.

## [0.2.2] - 2026-08-24

### Fixed
- `autocut --version` reported a stale hardcoded number. `__version__` is now
  read from the installed package metadata, so it always matches the released
  distribution version.

## [0.2.1] - 2026-08-24

### Changed
- **PyPI distribution name is now `trsdn-autocut`.** The plain `autocut` name on
  PyPI belongs to an unrelated project. The import package and the console
  command are unchanged — you still run `autocut` and `import autocut`; only
  `pip install trsdn-autocut` differs.

### Added
- Release workflow (`.github/workflows/release.yml`) publishing to PyPI via
  Trusted Publishing (GitHub Actions OIDC, no API tokens). Pushing a `v*` tag
  builds sdist + wheel, gates on `twine check --strict`, and publishes from the
  `pypi` environment.
- Explicit sdist file list so workspace folders and local config never end up in
  the published artifact.

## [0.2.0] - 2026-04-23

### Changed
- **LLM redundancy detection is now materially more aggressive.** The system
  prompt explicitly targets 15–25 % runtime reduction and enumerates the cut
  patterns (restatements, meta-narration, self-corrections, empty connective
  tissue, weak summaries) instead of a vague "focus on redundancy".
- Transcript is now sent to the LLM as sentences with a leading timestamp per
  line (break on sentence punctuation or ~140 chars) rather than one word per
  line. The model sees coherent clauses and produces longer, better-aligned
  cut ranges.
- Keyless local endpoints (llama.cpp, LM Studio, Ollama, internal gateways)
  are now fully supported: `is_configured()` accepts any non-default
  `base_url`, and the `Authorization` header is omitted when no API key is
  set.

### Measured impact
On a 12:14 German/English screen-demo (Parakeet-TDT v3, `gpt-5.4-mini` on a
local OpenAI-compatible endpoint) the LLM alone now removes ~137 s of semantic
redundancy (up from ~85 s), and the final cut shrinks from **7:48 → 6:13**
with default `talk` preset pauses.

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

[Unreleased]: https://github.com/trsdn/autocut/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/trsdn/autocut/releases/tag/v0.2.3
[0.2.2]: https://github.com/trsdn/autocut/releases/tag/v0.2.2
[0.2.1]: https://github.com/trsdn/autocut/releases/tag/v0.2.1
[0.2.0]: https://github.com/trsdn/autocut/releases/tag/v0.2.0
[0.1.0]: https://github.com/trsdn/autocut/releases/tag/v0.1.0
