"""Build cut plan from transcript + silences + optional LLM redundancy ranges."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from .silence import snap


FILLER_PATTERNS = {
    "en": r"^(um|uh|uhm|er|ah)[,.!?]?$",
    "de": r"^(äh|ähm|öh|öhm|hm)[,.!?]?$",
}


@dataclass
class Removal:
    kind: str        # "redundancy" | "filler" | "pause"
    start: float
    end: float
    note: str = ""


@dataclass
class CutPlan:
    source: str
    duration: float
    keep: list[tuple[float, float]]
    removed: list[Removal]

    def total_removed(self) -> float:
        return sum(r.end - r.start for r in self.removed)

    def write(self, path: Path):
        path.write_text(json.dumps({
            "source":   self.source,
            "duration": self.duration,
            "keep":     self.keep,
            "removed":  [asdict(r) for r in self.removed],
        }, indent=2))


def build_plan(
    *,
    source: str,
    duration: float,
    words: list[dict],
    silences_coarse: list[tuple[float, float]],   # -35dB, 0.25s
    silences_fine:   list[tuple[float, float]],   # -40dB, 0.15s
    language: str = "en",
    redundancy_ranges: list[tuple[float, float, str]] | None = None,
    protect_ranges: list[tuple[float, float]] | None = None,
    pause_trim_narrator_above: float = 0.35,
    pause_trim_narrator_keep:  float = 0.20,
    pause_trim_protected_above: float = 0.6,
    pause_trim_protected_keep:  float = 0.30,
    cut_fillers: bool = True,
    filler_pad: float = 0.06,
    min_keep: float = 0.10,
) -> CutPlan:
    protect_ranges = protect_ranges or []
    redundancy_ranges = redundancy_ranges or []

    def in_protected(s: float, e: float) -> bool:
        return any(s >= ps and e <= pe for ps, pe in protect_ranges)

    removals: list[Removal] = []

    # 1) Redundancy blocks (skip inside protected ranges)
    for s, e, note in redundancy_ranges:
        if in_protected(s, e):
            continue
        removals.append(Removal(
            kind="redundancy",
            start=snap(s, silences_coarse),
            end=snap(e, silences_coarse),
            note=note,
        ))

    # 2) Filler words (skip inside protected)
    if cut_fillers:
        rx = re.compile(FILLER_PATTERNS.get(language, FILLER_PATTERNS["en"]), re.I)
        for w in words:
            if not rx.match(w["word"]):
                continue
            s = snap(w["startTime"] - filler_pad, silences_fine, window=0.12)
            e = snap(w["endTime"]   + filler_pad, silences_fine, window=0.12)
            if in_protected(s, e):
                continue
            removals.append(Removal(kind="filler", start=s, end=e, note=w["word"]))

    # 3) Narrator pauses
    for s, e in silences_fine:
        dur = e - s
        if dur <= pause_trim_narrator_above: continue
        if in_protected(s, e): continue
        keep_s = pause_trim_narrator_keep
        mid = (s + e) / 2
        rs, re_ = mid - (dur - keep_s) / 2, mid + (dur - keep_s) / 2
        removals.append(Removal(kind="pause", start=rs, end=re_, note=f"{dur:.2f}s"))

    # 4) Protected-block pauses (more generous keep)
    for s, e in silences_coarse:
        if not in_protected(s, e): continue
        dur = e - s
        if dur <= pause_trim_protected_above: continue
        keep_s = pause_trim_protected_keep
        mid = (s + e) / 2
        rs, re_ = mid - (dur - keep_s) / 2, mid + (dur - keep_s) / 2
        removals.append(Removal(kind="pause", start=rs, end=re_, note=f"{dur:.2f}s (protected)"))

    # Merge overlapping removals
    removals.sort(key=lambda r: r.start)
    merged: list[Removal] = []
    for r in removals:
        if merged and r.start <= merged[-1].end + 0.02:
            prev = merged[-1]
            prev.end = max(prev.end, r.end)
            if r.kind not in prev.kind:
                prev.kind = f"{prev.kind}+{r.kind}"
        else:
            merged.append(r)

    # Invert → keep
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for r in merged:
        if r.start > cursor:
            keep.append((cursor, r.start))
        cursor = max(cursor, r.end)
    if cursor < duration:
        keep.append((cursor, duration))
    keep = [(s, e) for s, e in keep if e - s >= min_keep]

    return CutPlan(source=source, duration=duration, keep=keep, removed=merged)
