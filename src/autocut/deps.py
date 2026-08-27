"""Dependency detection and bootstrap (ffmpeg, fluidaudiocli)."""
from __future__ import annotations
import os
import platform
import shutil
import subprocess
from pathlib import Path

CACHE_DIR = Path(os.environ.get("AUTOCUT_CACHE",
                                Path.home() / ".cache" / "autocut"))

FLUIDAUDIO_REPO = "https://github.com/FluidInference/FluidAudio.git"


class DependencyError(RuntimeError):
    pass


def require(tool: str) -> str:
    """Return path to an external CLI tool or raise."""
    p = shutil.which(tool)
    if not p:
        raise DependencyError(
            f"'{tool}' not found in PATH.\n"
            f"Install: macOS → `brew install {tool}` · "
            f"Linux → `apt install {tool}` · "
            f"Windows → download from the official site."
        )
    return p


def check_ffmpeg() -> tuple[str, str]:
    return require("ffmpeg"), require("ffprobe")


# ---------------------------------------------------------------------------
# FluidAudio (macOS only) — Parakeet-TDT ASR with word-level timestamps.
# ---------------------------------------------------------------------------
def _fluidaudio_paths() -> tuple[Path, Path]:
    """Return (repo_dir, cli_binary) in the autocut cache."""
    repo = CACHE_DIR / "FluidAudio"
    cli  = repo / ".build" / "release" / "fluidaudiocli"
    return repo, cli


def find_fluidaudio() -> str | None:
    """Look for fluidaudiocli in PATH, env, then autocut cache."""
    if env := os.environ.get("AUTOCUT_FLUIDAUDIO_BIN"):
        if Path(env).exists():
            return env
    if p := shutil.which("fluidaudiocli"):
        return p
    _, cli = _fluidaudio_paths()
    return str(cli) if cli.exists() else None


def bootstrap_fluidaudio(log=print) -> str:
    """Clone and build FluidAudio CLI into the autocut cache.
    macOS only (CoreML + Swift toolchain)."""
    if platform.system() != "Darwin":
        raise DependencyError(
            "FluidAudio ASR backend requires macOS (uses CoreML + Swift).\n"
            "Use --asr-backend whisper-cpp on Linux/Windows."
        )
    require("git")
    require("swift")

    repo, cli = _fluidaudio_paths()
    repo.parent.mkdir(parents=True, exist_ok=True)

    if not repo.exists():
        log(f"Cloning FluidAudio → {repo}")
        subprocess.check_call(["git", "clone", "--depth", "1",
                               FLUIDAUDIO_REPO, str(repo)])

    if not cli.exists():
        log("Building fluidaudiocli (swift build -c release) — takes a minute…")
        subprocess.check_call(
            ["swift", "build", "-c", "release",
             "--product", "fluidaudiocli"],
            cwd=str(repo),
        )

    if not cli.exists():
        raise DependencyError(f"Build finished but binary missing at {cli}")
    return str(cli)


def ensure_fluidaudio(log=print) -> str:
    """Find or build fluidaudiocli. Returns path to binary."""
    if p := find_fluidaudio():
        return p
    return bootstrap_fluidaudio(log=log)


# ---------------------------------------------------------------------------
# whisper.cpp (cross-platform fallback)
# ---------------------------------------------------------------------------
def find_whisper_cpp() -> str | None:
    # whisper-cli (new name) or the old main binary
    for name in ("whisper-cli", "whisper-cpp", "main"):
        if p := shutil.which(name):
            return p
    return None


def require_whisper_cpp() -> str:
    p = find_whisper_cpp()
    if not p:
        raise DependencyError(
            "whisper.cpp not found. Install:\n"
            "  macOS:   brew install whisper-cpp\n"
            "  Linux:   see https://github.com/ggerganov/whisper.cpp\n"
            "  Windows: see https://github.com/ggerganov/whisper.cpp/releases"
        )
    return p
