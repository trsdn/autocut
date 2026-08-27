"""Shared fixtures.

The LLM config loader reads a real file under ``~/.config/autocut`` and a set of
``AUTOCUT_LLM_*`` environment variables. Tests must never pick those up from the
developer's machine, so anything touching :mod:`autocut.llm` uses ``clean_llm_env``.
"""
from __future__ import annotations

import pytest

LLM_ENV_VARS = (
    "AUTOCUT_LLM_BASE_URL",
    "AUTOCUT_LLM_API_KEY",
    "AUTOCUT_LLM_MODEL",
    "AUTOCUT_LLM_MAX_TOKENS",
    "AUTOCUT_LLM_TEMPERATURE",
)


@pytest.fixture
def clean_llm_env(monkeypatch, tmp_path):
    """Isolate LLMConfig from the host: no env vars, no config file on disk."""
    from autocut import llm

    for var in LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm, "CONFIG_PATH", tmp_path / "missing" / "config.json")
    return llm
