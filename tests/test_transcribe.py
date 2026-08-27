"""ASR backend dispatch and the whisper.cpp -> autocut transcript normalisation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from autocut import transcribe as transcribe_mod
from autocut.transcribe import transcribe, transcribe_whisper_cpp


def test_an_unknown_backend_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown ASR backend"):
        transcribe(tmp_path / "a.wav", tmp_path / "a.json", backend="sphinx")


def test_whisper_cpp_without_a_model_is_rejected_before_running_anything(tmp_path):
    with pytest.raises(ValueError, match="--whisper-model required"):
        transcribe(tmp_path / "a.wav", tmp_path / "a.json", backend="whisper-cpp")


@pytest.fixture
def whisper(monkeypatch):
    """Stub out the whisper.cpp binary; the test supplies its raw JSON output."""
    calls: list[list[str]] = []

    monkeypatch.setattr(transcribe_mod, "require_whisper_cpp", lambda: "/bin/whisper-cli")
    monkeypatch.setattr(subprocess, "check_call", lambda cmd, **kw: calls.append(cmd))
    return calls


RAW_WHISPER = {
    "transcription": [
        {
            "tokens": [
                {"text": " Hello", "offsets": {"from": 0, "to": 500}, "p": 0.98},
                {"text": "[_BEG_]", "offsets": {"from": 500, "to": 500}, "p": 1.0},
                {"text": " world", "offsets": {"from": 500, "to": 1250}, "p": 0.91},
                {"text": "   ", "offsets": {"from": 1250, "to": 1260}, "p": 1.0},
            ]
        },
        {"tokens": [{"text": "again", "offsets": {"from": 2000, "to": 2500}, "p": 0.8}]},
    ]
}


def run_whisper(tmp_path: Path) -> dict:
    out_json = tmp_path / "transcript.json"
    out_json.write_text(json.dumps(RAW_WHISPER))
    return transcribe_whisper_cpp(tmp_path / "a.wav", out_json, "ggml-base.bin",
                                  log=lambda *_: None)


def test_millisecond_offsets_become_seconds(tmp_path, whisper):
    doc = run_whisper(tmp_path)

    assert doc["wordTimings"][0]["startTime"] == pytest.approx(0.0)
    assert doc["wordTimings"][0]["endTime"] == pytest.approx(0.5)
    assert doc["wordTimings"][1]["endTime"] == pytest.approx(1.25)


def test_special_marker_tokens_are_dropped(tmp_path, whisper):
    doc = run_whisper(tmp_path)

    assert "[_BEG_]" not in [w["word"] for w in doc["wordTimings"]]


def test_whitespace_only_tokens_are_dropped(tmp_path, whisper):
    doc = run_whisper(tmp_path)

    assert all(w["word"] for w in doc["wordTimings"])


def test_tokens_are_stripped_and_segments_are_flattened(tmp_path, whisper):
    doc = run_whisper(tmp_path)

    assert [w["word"] for w in doc["wordTimings"]] == ["Hello", "world", "again"]


def test_per_token_probability_is_carried_over_as_confidence(tmp_path, whisper):
    doc = run_whisper(tmp_path)

    assert doc["wordTimings"][0]["confidence"] == pytest.approx(0.98)


def test_a_plain_text_rendering_is_included(tmp_path, whisper):
    doc = run_whisper(tmp_path)

    assert doc["text"] == "Hello world again"


def test_the_normalised_transcript_replaces_the_raw_file_on_disk(tmp_path, whisper):
    """The rest of the pipeline reads this file back, so it must be autocut's schema."""
    doc = run_whisper(tmp_path)
    on_disk = json.loads((tmp_path / "transcript.json").read_text())

    assert on_disk == doc
    assert "transcription" not in on_disk


def test_word_level_timestamps_are_requested_from_whisper(tmp_path, whisper):
    run_whisper(tmp_path)

    cmd = whisper[0]
    assert cmd[0] == "/bin/whisper-cli"
    assert "--output-json-full" in cmd
    # -ml 1 forces at most one word per segment, which is what gives word timings.
    assert cmd[cmd.index("-ml") + 1] == "1"
    assert cmd[cmd.index("-m") + 1] == "ggml-base.bin"
