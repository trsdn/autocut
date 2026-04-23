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
        # Either an api key is set, or a non-default (likely local) endpoint
        return bool(self.api_key) or self.base_url != "https://api.openai.com/v1"


SYSTEM_PROMPT = """You are a ruthless video editor shortening a lecture/demo
transcript for a tight YouTube cut. Your goal is to REMOVE 15-25% of
the runtime by cutting passages that add no new information.

CUT these patterns aggressively:
- Restatements: the same idea expressed twice in different words
  ("...we can do X. So what that means is we can do X.")
- Meta-narration before getting to the point
  ("so let me now show you..." — cut, keep the thing being shown)
- Self-corrections and mid-sentence restarts
  ("we have um, sorry we will create..." — cut the aborted clause)
- Verbose connective tissue that can be replaced by a hard cut
  ("so now, what we can do then, as you can see...")
- Filler phrases: "you know", "sort of", "essentially", "basically",
  "obviously" when semantically empty
- Summaries of what was just said ("so that was X")
- Weak conclusions ("so yeah, that's it") unless final sentence

DO NOT cut:
- New factual content or first mention of a concept
- Concrete examples (even if long)
- Any timestamp inside PROTECTED ranges
- The single final sign-off sentence

Aim for 12-25 ranges totalling 90-200 seconds removed for a ~10-minute
transcript. Prefer a smaller number of longer coherent ranges over many
tiny slices.

OUTPUT: JSON array only. Each item: {"start": <sec>, "end": <sec>, "reason": "..."}
Timestamps must be real word boundaries present in the transcript.
No prose, no markdown, only the JSON array.
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
            **({"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}),
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
    # Render as readable sentences with a leading timestamp per line.
    # A "line" breaks after sentence-ending punctuation OR after ~140 chars.
    lines: list[str] = []
    buf: list[str] = []
    line_start: float | None = None
    line_chars = 0
    for w in words:
        if line_start is None:
            line_start = float(w["startTime"])
        tok = str(w["word"])
        buf.append(tok)
        line_chars += len(tok) + 1
        ends_sentence = tok.endswith((".", "?", "!"))
        if ends_sentence or line_chars >= 140:
            lines.append(f"[{line_start:7.2f}] {' '.join(buf)}")
            buf = []
            line_start = None
            line_chars = 0
    if buf:
        lines.append(f"[{line_start or 0:7.2f}] {' '.join(buf)}")
    transcript = "\n".join(lines)

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
