# AGENTS.md

Guidance for AI coding agents working in this repository. Everything here has
been executed against this tree; commands are copy-pasteable.

## The one rule that overrides convenience

**autocut has zero runtime Python dependencies, and that is deliberate.**

```toml
# pyproject.toml
# Intentionally zero runtime python dependencies: stdlib only.
dependencies = []
```

Do not add anything to `[project].dependencies`. Not `requests`, not `openai`,
not `pydantic`, not `numpy`. The whole point is that `pip install trsdn-autocut`
pulls nothing and cannot break someone's environment.

Consequences you must live with:

- HTTP is `urllib.request`, not `requests` (see `llm.py`).
- The OpenAI-compatible client is ~20 lines of hand-rolled JSON over `urllib`.
  Do not replace it with the `openai` SDK.
- Config parsing is `json`, not `pydantic`/`attrs`.
- Heavy ASR machinery (`torch`, `nemo_toolkit`, `soundfile`, `numpy`) lives
  behind the `nemo` **optional** extra and must only ever be imported *inside a
  function*, never at module level — see `nemo_backend.py`.
- External binaries (`ffmpeg`, `ffprobe`, `fluidaudiocli`, `whisper-cli`) are
  discovered at runtime via `deps.py`, not vendored or pip-installed.

Three tests enforce this and will fail the build if you break it:
`test_the_runtime_has_no_third_party_dependencies`,
`test_modules_import_only_the_standard_library_at_import_time`, and a CI step
that inspects the installed distribution metadata.

Test-only and build-only dependencies (`pytest`, `ruff`, `mypy`, `hatchling`)
are fine — they are not runtime dependencies.

## Setup

Requires Python >= 3.10 and `ffmpeg` + `ffprobe` on `PATH`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Do not create a virtualenv inside the repository under a name other than
`.venv`/`venv`; `hatchling` will otherwise sweep files out of it into the built
sdist.

## Commands

Run these from the repository root. All four are what CI runs.

| Task | Command |
| --- | --- |
| Test | `pytest` |
| Lint | `ruff check .` |
| Type check | `mypy` |
| Build | `python -m build && twine check --strict dist/*` |

Notes:

- `pytest`, `ruff` and `mypy` need no arguments — `testpaths`, `select` and
  `files` are configured in `pyproject.toml`.
- `python -m build` needs `pip install build twine` (not part of the `dev`
  extra, matching how CI installs it).
- The end-to-end test in `tests/test_integration.py` synthesises a clip with
  `ffmpeg` and drives the real binary. It **skips itself** when `ffmpeg` is
  missing, so a green local run without ffmpeg is not a full run.
- Smoke test the CLI with `autocut --version`.

## Architecture

A single linear pipeline, one module per stage. `cli.py` is the only place that
orchestrates; every other module is independently callable.

```
input video
  │
  ├─ audio.py      extract_wav_16k_mono()   ffmpeg → 16 kHz mono WAV
  │                probe_duration()         ffprobe → seconds
  │
  ├─ transcribe.py transcribe()             dispatch by --asr-backend
  │                  ├─ fluidaudio  → deps.ensure_fluidaudio() (macOS, CoreML)
  │                  ├─ nemo        → nemo_backend.py (optional extra)
  │                  └─ whisper-cpp → normalised to autocut's schema
  │                                         → {"wordTimings": [...]}
  │
  ├─ silence.py    detect_silences()        ffmpeg silencedetect, twice:
  │                                         coarse -35 dB/0.25 s, fine -40 dB/0.15 s
  │                snap()                   nudge a cut to a real silence boundary
  │
  ├─ llm.py        find_redundancies()      optional; OpenAI-compatible endpoint
  │                                         → [(start, end, reason)]
  │
  ├─ plan.py       build_plan()             THE core logic → CutPlan
  │                                         redundancy + fillers + pauses,
  │                                         merge overlaps, invert to `keep`
  │
  └─ render.py     render()                 one big ffmpeg filter_complex:
                                            speed → trim → fade → concat →
                                            highpass → compressor → de-ess → loudnorm
```

Key data shapes:

- **Word timing**: `{"word": str, "startTime": float, "endTime": float, "confidence": float}`.
  Every backend must normalise to this. Times are seconds.
- **`CutPlan`** (`plan.py`): `keep` is a list of `(start, end)` to retain;
  `removed` is a list of `Removal(kind, start, end, note)` where `kind` is
  `"redundancy" | "filler" | "pause"` or a `+`-joined combination after merging.

Two things that are easy to get wrong:

1. **Timeline scaling.** Silences and word timings are detected on the
   *original* audio, but the cut plan and `render()` operate on the
   *post-speed* timeline. `cli.py` rescales everything by `1/speed` before
   calling `build_plan`. `--protect` ranges are given by the user in post-speed
   time already.
2. **Protected ranges do not freeze a block.** `--protect` skips redundancy and
   filler cuts, and skips *narrator* pause trimming, but long pauses inside a
   protected range are still trimmed using the more generous
   `pause_trim_protected_above` / `pause_trim_protected_keep` values.

Caching: `output/<stem>/.work/` holds `audio_16k.wav`, `transcript.json` and
`cut_plan.json`. Re-runs reuse them, so delete that directory when changing
extraction or transcription behaviour.

## Conventions

- **Style is deliberate.** The source uses column-aligned assignments and
  compact `if cond: stmt` one-liners. Ruff is configured defect-focused
  (`E4`, `E7`, `E9`, `F`, `B`) precisely so it does not fight this. Do not run a
  formatter over the tree and do not "fix" alignment.
- `from __future__ import annotations` at the top of every module; modern
  builtin generics (`list[tuple[float, float]]`) in signatures.
- Keyword-only arguments (`*`) for functions with many knobs — `build_plan` and
  `render` both do this. Keep it.
- Modules take injected dependencies (`ffmpeg` path, `log=print`) rather than
  reaching for globals, which is what makes them testable without patching.
- User-facing progress goes to stdout with a `→` prefix; errors go to stderr
  prefixed `error:` and `main()` returns a non-zero int (it does not raise).
- New CLI flags belong in the matching `add_argument_group` in
  `cli.build_parser`, and presets in `PRESETS` must all define the same keys.

## Testing conventions

- Tests mirror the module they cover: `tests/test_<module>.py`.
- Test names are sentences describing the behaviour
  (`test_short_narrator_pause_is_left_alone`), not `test_func_1`.
- Never call a real external binary in a unit test — patch `subprocess` and
  assert on the command that *would* have run. `tests/test_render.py` and
  `tests/test_silence.py` show the pattern. The only exception is
  `tests/test_integration.py`, which is explicitly guarded by a skip.
- Anything touching `llm.py` must use the `clean_llm_env` fixture, or it will
  pick up the developer's real `~/.config/autocut/config.json` and
  `AUTOCUT_LLM_*` environment variables.
- Compare floats with `pytest.approx`; the pipeline is full of derived
  timestamps that are not exactly representable.

## Releasing

Releasing is **already automated and already works** — do not add a second
publishing path.

`.github/workflows/release.yml` publishes to PyPI via Trusted Publishing
(GitHub Actions OIDC, `id-token: write`, `pypa/gh-action-pypi-publish`). There
is no `PYPI_API_TOKEN` and there must never be one.

To release: bump `version` in `pyproject.toml`, add a `CHANGELOG.md` section,
commit to `main`, then `git tag vX.Y.Z && git push origin vX.Y.Z`.

- The distribution is named **`trsdn-autocut`**, not `autocut` — the plain name
  on PyPI belongs to an unrelated project. The import package and console
  command are still `autocut`.
- `__version__` is read from installed metadata, so it follows `pyproject.toml`
  automatically. A test asserts they agree.
- A version can only be uploaded to PyPI once. Bump again rather than trying to
  replace a published release.
- Agents must never run `twine upload` or otherwise publish by hand.
