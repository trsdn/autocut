"""Optional LLM-based redundancy detection via OpenAI-compatible API.

Config precedence:
  1. CLI flags (--llm-*)
  2. Env vars (AUTOCUT_LLM_BASE_URL, AUTOCUT_LLM_API_KEY, AUTOCUT_LLM_MODEL)
  3. Config file ~/.config/autocut/config.json

Stdlib-only: uses urllib. No `openai` dependency.
"""
from __future__ import annotations
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


CONFIG_PATH = Path(
    os.environ.get("AUTOCUT_CONFIG",
                   Path.home() / ".config" / "autocut" / "config.json")
)


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key:  str = ""
    model:    str = "gpt-5.4-mini"
    # Large default to accommodate long transcripts; gpt-5.4-mini supports
    # a multi-hundred-k context window.
    max_tokens:  int = 16384
    temperature: float = 0.1

    @classmethod
    def load(cls, cli: dict | None = None) -> "LLMConfig":
        data: dict = {}
        if CONFIG_PATH.exists():
            data.update(json.loads(CONFIG_PATH.read_text()).get("llm", {}))
        for k, env in (("base_url",    "AUTOCUT_LLM_BASE_URL"),
                       ("api_key",     "AUTOCUT_LLM_API_KEY"),
                       ("model",       "AUTOCUT_LLM_MODEL"),
                       ("max_tokens",  "AUTOCUT_LLM_MAX_TOKENS"),
                       ("temperature", "AUTOCUT_LLM_TEMPERATURE")):
            if v := os.environ.get(env):
                data[k] = int(v) if k == "max_tokens" else (
                    float(v) if k == "temperature" else v)
        if cli:
            data.update({k: v for k, v in cli.items() if v is not None})
        return cls(**data)

    def is_configured(self) -> bool:
        return bool(self.api_key)


SYSTEM_PROMPT = """You analyze lecture/demo transcripts with word-level timestamps
and identify passages to CUT for a tighter edit.

Focus on:
- Redundancy: the same idea stated twice (e.g. restated in a synonym)
- Umformulierungen: mid-sentence self-corrections that add no info
- Weak filler phrases (NOT single filler words — those are handled elsewhere)
- Self-interruptions and aborted restarts

DO NOT cut:
- Substantive content, even if verbose
- Examples, even if long
- Passages in the "PROTECTED" ranges provided by the user

Return a JSON array of objects: {"start": <sec>, "end": <sec>, "reason": "..."}
Timestamps must correspond to actual word boundaries in the transcript.
No prose, only JSON.
"""


def _chat(cfg: LLMConfig, messages: list[dict]) -> str:
    body = json.dumps({
        "model":       cfg.model,
        "messages":    messages,
        "temperature": cfg.temperature,
        "max_tokens":  cfg.max_tokens,
    }).encode()
    req = urllib.request.Request(
        f"{cfg.base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = json.load(r)
    return payload["choices"][0]["message"]["content"]


def find_redundancies(
    words: list[dict],
    *,
    cfg: LLMConfig,
    protect_ranges: list[tuple[float, float]] | None = None,
    log=print,
) -> list[tuple[float, float, str]]:
    """Ask the LLM for redundancy ranges. Returns [(start, end, reason)]."""
    if not cfg.is_configured():
        log("LLM not configured, skipping semantic redundancy detection.")
        return []

    protected = protect_ranges or []
    transcript_lines = []
    for w in words:
        transcript_lines.append(f"[{w['startTime']:7.2f}] {w['word']}")
    transcript = "\n".join(transcript_lines)

    user = (
        f"PROTECTED ranges (never cut inside): {protected}\n\n"
        f"TRANSCRIPT (timestamp in seconds, one word per line):\n{transcript}\n\n"
        "Return JSON array of cut ranges."
    )
    log(f"LLM: calling {cfg.model} at {cfg.base_url} "
        f"({len(words)} words, ~{len(transcript)//1000}k chars)")
    reply = _chat(cfg, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user},
    ])
    # Extract the first JSON array (tolerate code fences / prose)
    m = re.search(r"\[[\s\S]*\]", reply)
    if not m:
        log("LLM returned no JSON array, ignoring.")
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        log("LLM JSON parse failed, ignoring.")
        return []

    out: list[tuple[float, float, str]] = []
    for it in items:
        try:
            s = float(it["start"]); e = float(it["end"])
            reason = str(it.get("reason", ""))[:80]
            if e > s: out.append((s, e, reason))
        except (KeyError, TypeError, ValueError):
            continue
    log(f"LLM suggested {len(out)} cut ranges.")
    return out
