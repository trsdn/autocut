"""ASR backends: produce word-level timings JSON."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from .deps import ensure_fluidaudio, require_whisper_cpp


def transcribe_fluidaudio(audio_wav: Path, out_json: Path,
                          variant: str = "v3", log=print) -> dict:
    """Run fluidaudiocli transcribe with word timings.
    Requires macOS. Uses Parakeet-TDT-0.6B v3 by default (multilingual)."""
    binary = ensure_fluidaudio(log=log)
    log(f"ASR: FluidAudio ({variant}) → {audio_wav.name}")
    subprocess.check_call([
        binary, "transcribe", str(audio_wav),
        "--word-timestamps",
        "--output-json", str(out_json),
    ])
    return json.load(open(out_json))


def transcribe_whisper_cpp(audio_wav: Path, out_json: Path,
                           model: str, log=print) -> dict:
    """Run whisper.cpp with word-level timestamps.
    `model` is a path to a ggml-*.bin model file."""
    binary = require_whisper_cpp()
    log(f"ASR: whisper.cpp ({Path(model).name}) → {audio_wav.name}")
    subprocess.check_call([
        binary, "-m", model, "-f", str(audio_wav),
        "--output-json-full", "-of", str(out_json.with_suffix("")),
        "-ml", "1",  # max 1 word per segment → word-level
    ])
    raw = json.load(open(out_json))
    # Normalize to autocut schema: {"wordTimings":[{startTime,endTime,word}]}
    words = []
    for seg in raw.get("transcription", []):
        for tok in seg.get("tokens", []):
            t = tok.get("text", "").strip()
            if not t or t.startswith("["): continue
            off = tok.get("offsets", {})
            words.append({
                "word": t,
                "startTime": off.get("from", 0) / 1000.0,
                "endTime":   off.get("to",   0) / 1000.0,
                "confidence": tok.get("p", 1.0),
            })
    norm = {"wordTimings": words, "text": " ".join(w["word"] for w in words)}
    out_json.write_text(json.dumps(norm, indent=2))
    return norm


def transcribe(audio_wav: Path, out_json: Path, backend: str,
               whisper_model: str | None = None,
               nemo_model: str | None = None,
               log=print) -> dict:
    if backend == "fluidaudio":
        return transcribe_fluidaudio(audio_wav, out_json, log=log)
    if backend == "whisper-cpp":
        if not whisper_model:
            raise ValueError("--whisper-model required for whisper-cpp backend")
        return transcribe_whisper_cpp(audio_wav, out_json, whisper_model, log=log)
    if backend == "nemo":
        from .nemo_backend import transcribe_nemo, DEFAULT_MODEL
        return transcribe_nemo(audio_wav, out_json,
                               model_name=nemo_model or DEFAULT_MODEL, log=log)
    raise ValueError(f"Unknown ASR backend: {backend}")
