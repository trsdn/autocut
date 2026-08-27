"""CLI argument handling, presets and input resolution."""
from __future__ import annotations

import pytest

from autocut.cli import PRESETS, VIDEO_EXT, build_parser, main, parse_range, resolve_input


def touch(path, mtime: float | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")
    if mtime is not None:
        import os

        os.utime(path, (mtime, mtime))
    return path


# --------------------------------------------------------------------------
# parse_range
# --------------------------------------------------------------------------
def test_parse_range_reads_a_start_end_pair():
    assert parse_range("12.5:30") == (12.5, 30.0)


def test_parse_range_accepts_integers():
    assert parse_range("0:5") == (0.0, 5.0)


@pytest.mark.parametrize("bad", ["12.5", "a:b", "1:2:3", ""])
def test_parse_range_rejects_malformed_input(bad):
    with pytest.raises(ValueError):
        parse_range(bad)


# --------------------------------------------------------------------------
# resolve_input
# --------------------------------------------------------------------------
def test_an_existing_path_is_used_as_given(tmp_path):
    clip = touch(tmp_path / "elsewhere" / "clip.mp4")

    assert resolve_input(clip, tmp_path) == clip


def test_a_bare_filename_is_looked_up_in_the_input_folder(tmp_path):
    from pathlib import Path

    clip = touch(tmp_path / "input" / "clip.mp4")

    assert resolve_input(Path("clip.mp4"), tmp_path) == clip


def test_a_missing_name_reports_both_paths_it_tried(tmp_path):
    from pathlib import Path

    (tmp_path / "input").mkdir()

    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_input(Path("nope.mp4"), tmp_path)

    message = str(excinfo.value)
    assert "nope.mp4" in message
    assert "input" in message


def test_omitting_the_input_picks_the_newest_video(tmp_path):
    touch(tmp_path / "input" / "old.mp4", mtime=1_000_000)
    newest = touch(tmp_path / "input" / "new.mov", mtime=2_000_000)
    touch(tmp_path / "input" / "middle.mkv", mtime=1_500_000)

    assert resolve_input(None, tmp_path) == newest


def test_non_video_files_are_ignored_when_autoselecting(tmp_path):
    touch(tmp_path / "input" / "notes.txt", mtime=9_000_000)
    touch(tmp_path / "input" / "subs.srt", mtime=9_000_000)
    clip = touch(tmp_path / "input" / "clip.mp4", mtime=1_000_000)

    assert resolve_input(None, tmp_path) == clip


def test_video_extension_matching_is_case_insensitive(tmp_path):
    clip = touch(tmp_path / "input" / "CLIP.MP4")

    assert resolve_input(None, tmp_path) == clip


def test_a_missing_input_folder_is_an_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        resolve_input(None, tmp_path)


def test_an_empty_input_folder_is_an_actionable_error(tmp_path):
    (tmp_path / "input").mkdir()

    with pytest.raises(FileNotFoundError, match="No video files"):
        resolve_input(None, tmp_path)


def test_the_common_container_formats_are_recognised():
    assert {".mp4", ".mov", ".mkv", ".webm"} <= VIDEO_EXT


# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------
def test_every_preset_defines_the_same_knobs():
    expected = set(PRESETS["talk"])

    assert expected == {
        "speed",
        "cut_fillers",
        "pause_narrator_above",
        "pause_narrator_keep",
        "pause_protected_above",
        "pause_protected_keep",
    }
    for name, preset in PRESETS.items():
        assert set(preset) == expected, f"preset {name!r} has a different shape"


def test_every_preset_keeps_less_than_it_trims_from():
    """`keep` must be below the trim threshold or trimming would lengthen pauses."""
    for name, preset in PRESETS.items():
        assert preset["pause_narrator_keep"] < preset["pause_narrator_above"], name
        assert preset["pause_protected_keep"] < preset["pause_protected_above"], name


def test_every_preset_protects_more_than_it_trims_narration():
    for name, preset in PRESETS.items():
        assert preset["pause_protected_above"] > preset["pause_narrator_above"], name


def test_the_meeting_preset_preserves_turn_taking():
    assert PRESETS["meeting"]["cut_fillers"] is False
    assert PRESETS["meeting"]["pause_narrator_above"] > PRESETS["talk"]["pause_narrator_above"]


def test_the_vlog_preset_is_the_most_aggressive():
    assert PRESETS["vlog"]["pause_narrator_above"] < PRESETS["talk"]["pause_narrator_above"]
    assert PRESETS["vlog"]["speed"] > 1.0


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def test_defaults_match_the_documented_talk_preset():
    args = build_parser().parse_args([])

    assert args.preset == "talk"
    assert args.language == "en"
    assert args.asr_backend == "fluidaudio"
    assert args.silence_db == -35.0
    assert args.silence_db_fine == -40.0
    assert args.fade_ms == 40
    assert args.llm is False
    assert args.dry_run is False


def test_protect_is_repeatable_and_parsed_into_pairs():
    args = build_parser().parse_args(["--protect", "1:2", "--protect", "10:20.5"])

    assert args.protect == [(1.0, 2.0), (10.0, 20.5)]


def test_an_unknown_preset_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--preset", "podcast"])


def test_an_unknown_language_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--language", "es"])


def test_version_reports_the_installed_package_version(capsys):
    import autocut

    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"autocut {autocut.__version__}"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def test_main_exits_with_code_2_when_the_input_cannot_be_resolved(tmp_path, capsys):
    """Fails before touching ffmpeg, so this is safe on a machine without it."""
    assert main(["--root", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


def test_main_exits_with_code_2_when_ffmpeg_is_missing(tmp_path, capsys, monkeypatch):
    from autocut import cli
    from autocut.deps import DependencyError

    touch(tmp_path / "input" / "clip.mp4")

    def no_ffmpeg():
        raise DependencyError("'ffmpeg' not found in PATH.")

    monkeypatch.setattr(cli, "check_ffmpeg", no_ffmpeg)

    assert main(["--root", str(tmp_path)]) == 2
    assert "ffmpeg" in capsys.readouterr().err
