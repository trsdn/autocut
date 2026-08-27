"""Shared fixtures.

The LLM config loader reads a real file under ``~/.config/autocut`` and a set of
``AUTOCUT_LLM_*`` environment variables. Tests must never pick those up from the
developer's machine, so anything touching :mod:`autocut.llm` uses ``clean_llm_env``.
"""
from __future__ import annotations

import os

import pytest

LLM_ENV_VARS = (
    "AUTOCUT_LLM_BASE_URL",
    "AUTOCUT_LLM_API_KEY",
    "AUTOCUT_LLM_MODEL",
    "AUTOCUT_LLM_MAX_TOKENS",
    "AUTOCUT_LLM_TEMPERATURE",
)


def unavailable(reason: str, *, ci_remedy: str) -> None:
    """Skip on a developer machine; fail on CI.

    Some checks depend on things the environment has to supply — an external
    binary, or a clone that actually carries its tags. Locally their absence is
    ordinary: a fresh clone or a machine without ffmpeg is a fair reason to sit
    a test out.

    On CI it is never ordinary. There the environment is built by the workflow,
    so a missing dependency means the *workflow* is wrong — and skipping turns
    that into a green run, which is the failure this helper exists to prevent.
    A guard that declines to run where it matters most reports exactly what a
    passing guard reports.

    `ci_remedy` is surfaced in the failure so whoever meets it knows which
    workflow step went missing.
    """
    if os.environ.get("CI"):
        pytest.fail(
            f"{reason}\n\n"
            "This is a skip on a developer machine, but a failure on CI: the "
            "workflow is responsible for providing this, so its absence means "
            "the workflow is broken and the check below never ran.\n\n"
            f"Fix: {ci_remedy}"
        )
    pytest.skip(reason)


@pytest.fixture
def clean_llm_env(monkeypatch, tmp_path):
    """Isolate LLMConfig from the host: no env vars, no config file on disk."""
    from autocut import llm

    for var in LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm, "CONFIG_PATH", tmp_path / "missing" / "config.json")
    return llm
