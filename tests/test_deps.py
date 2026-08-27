"""External tool discovery. autocut shells out; these guard the lookup rules."""
from __future__ import annotations

import platform
import shutil

import pytest

from autocut import deps
from autocut.deps import (
    DependencyError,
    check_ffmpeg,
    find_fluidaudio,
    find_whisper_cpp,
    require,
    require_whisper_cpp,
)


@pytest.fixture
def which(monkeypatch):
    """Control PATH lookups: `which.table` maps tool name -> resolved path."""

    class Which:
        table: dict[str, str] = {}

        def __call__(self, name):
            return self.table.get(name)

    stub = Which()
    stub.table = {}
    monkeypatch.setattr(shutil, "which", stub)
    return stub


def test_require_returns_the_resolved_path(which):
    which.table = {"ffmpeg": "/opt/homebrew/bin/ffmpeg"}

    assert require("ffmpeg") == "/opt/homebrew/bin/ffmpeg"


def test_require_raises_with_per_platform_install_instructions(which):
    with pytest.raises(DependencyError) as excinfo:
        require("ffmpeg")

    message = str(excinfo.value)
    assert "'ffmpeg' not found in PATH" in message
    assert "brew install ffmpeg" in message
    assert "apt install ffmpeg" in message


def test_check_ffmpeg_returns_both_binaries(which):
    which.table = {"ffmpeg": "/bin/ffmpeg", "ffprobe": "/bin/ffprobe"}

    assert check_ffmpeg() == ("/bin/ffmpeg", "/bin/ffprobe")


def test_check_ffmpeg_fails_when_only_ffmpeg_is_installed(which):
    """ffprobe is a separate binary in some distributions and is also required."""
    which.table = {"ffmpeg": "/bin/ffmpeg"}

    with pytest.raises(DependencyError, match="ffprobe"):
        check_ffmpeg()


@pytest.mark.parametrize("name", ["whisper-cli", "whisper-cpp", "main"])
def test_whisper_cpp_is_found_under_any_of_its_binary_names(which, name):
    which.table = {name: f"/bin/{name}"}

    assert find_whisper_cpp() == f"/bin/{name}"


def test_the_modern_whisper_cli_name_wins_over_the_legacy_one(which):
    which.table = {"whisper-cli": "/bin/whisper-cli", "main": "/bin/main"}

    assert find_whisper_cpp() == "/bin/whisper-cli"


def test_find_whisper_cpp_returns_none_when_absent(which):
    assert find_whisper_cpp() is None


def test_require_whisper_cpp_points_at_the_upstream_project(which):
    with pytest.raises(DependencyError, match="whisper.cpp"):
        require_whisper_cpp()


def test_an_explicit_fluidaudio_binary_overrides_discovery(which, tmp_path, monkeypatch):
    binary = tmp_path / "fluidaudiocli"
    binary.write_bytes(b"")
    monkeypatch.setenv("AUTOCUT_FLUIDAUDIO_BIN", str(binary))
    which.table = {"fluidaudiocli": "/usr/local/bin/fluidaudiocli"}

    assert find_fluidaudio() == str(binary)


def test_a_stale_fluidaudio_override_falls_back_to_path(which, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCUT_FLUIDAUDIO_BIN", str(tmp_path / "gone"))
    which.table = {"fluidaudiocli": "/usr/local/bin/fluidaudiocli"}

    assert find_fluidaudio() == "/usr/local/bin/fluidaudiocli"


def test_a_previously_bootstrapped_build_in_the_cache_is_reused(which, tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOCUT_FLUIDAUDIO_BIN", raising=False)
    monkeypatch.setattr(deps, "CACHE_DIR", tmp_path)
    built = tmp_path / "FluidAudio" / ".build" / "release" / "fluidaudiocli"
    built.parent.mkdir(parents=True)
    built.write_bytes(b"")

    assert find_fluidaudio() == str(built)


def test_nothing_anywhere_reports_no_fluidaudio(which, tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOCUT_FLUIDAUDIO_BIN", raising=False)
    monkeypatch.setattr(deps, "CACHE_DIR", tmp_path)

    assert find_fluidaudio() is None


def test_bootstrapping_fluidaudio_off_macos_suggests_the_portable_backend(monkeypatch):
    """FluidAudio is CoreML + Swift; on Linux/Windows it can never be built."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    with pytest.raises(DependencyError) as excinfo:
        deps.bootstrap_fluidaudio(log=lambda *_: None)

    assert "whisper-cpp" in str(excinfo.value)
