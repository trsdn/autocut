"""NeMo Parakeet backend (cross-platform, requires torch + nemo_toolkit).

Install: `pip install 'autocut[nemo]'`

Runs chunked inference to avoid OOM on long audio: processes 30 s windows with
2 s overlap, extracts word timestamps via RNNT hypothesis alignments, and
merges them back to an absolute timeline.

Model: `nvidia/parakeet-tdt-0.6b-v3` (same as FluidAudio backend, multilingual).
"""
from __future__ import annotations
import json
from pathlib import Path


DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
CHUNK_SEC = 30.0
OVERLAP_SEC = 2.0


def _import_nemo():
    try:
        import soundfile as sf            # noqa: F401
        import numpy as np                # noqa: F401
        from nemo.collections.asr.models import ASRModel  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "NeMo backend requires extra deps. Install with:\n"
            "  pip install 'autocut[nemo]'\n"
            f"(missing: {e.name})"
        ) from e


def transcribe_nemo(audio_wav: Path, out_json: Path,
                    model_name: str = DEFAULT_MODEL,
                    log=print) -> dict:
    _import_nemo()
    import numpy as np
    import soundfile as sf
    from nemo.collections.asr.models import ASRModel

    log(f"ASR: NeMo Parakeet ({model_name}) loading model…")
    model = ASRModel.from_pretrained(model_name)
    model.eval()

    audio, sr = sf.read(str(audio_wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        raise ValueError(f"Expected 16 kHz WAV, got {sr} Hz")

    total_sec = len(audio) / sr
    step = CHUNK_SEC - OVERLAP_SEC
    chunks = []
    t = 0.0
    while t < total_sec:
        chunks.append((t, min(t + CHUNK_SEC, total_sec)))
        t += step

    log(f"ASR: {total_sec:.1f}s → {len(chunks)} chunks of {CHUNK_SEC:.0f}s")

    all_words: list[dict] = []
    for i, (s, e) in enumerate(chunks):
        seg = audio[int(s * sr):int(e * sr)]
        hyps = model.transcribe(
            [seg],
            batch_size=1,
            return_hypotheses=True,
            timestamps=True,
        )
        hyp = hyps[0][0] if isinstance(hyps, tuple) else hyps[0]
        ts = getattr(hyp, "timestamp", None) or {}
        words = ts.get("word") or []
        for w in words:
            ws = float(w.get("start", 0.0)) + s
            we = float(w.get("end",   0.0)) + s
            token = w.get("word") or w.get("text") or ""
            if not token:
                continue
            # Dedup overlap: drop if last word ends after this word's start
            if all_words and ws < all_words[-1]["endTime"] - 0.05:
                continue
            all_words.append({
                "word":      token,
                "startTime": ws,
                "endTime":   we,
                "confidence": 1.0,
            })
        log(f"  chunk {i+1}/{len(chunks)}  [{s:6.1f}–{e:6.1f}]  "
            f"+{len(words)} words  (total {len(all_words)})")

    doc = {
        "wordTimings": all_words,
        "text": " ".join(w["word"] for w in all_words),
        "duration": total_sec,
        "model": model_name,
    }
    out_json.write_text(json.dumps(doc, indent=2))
    return doc
