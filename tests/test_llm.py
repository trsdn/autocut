"""LLM redundancy detection: config precedence, prompt shape, response parsing."""
from __future__ import annotations

import json

import pytest

from autocut.llm import LLMConfig, find_redundancies


def words(*pairs) -> list[dict]:
    return [{"word": w, "startTime": s, "endTime": e} for w, s, e in pairs]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def test_defaults_point_at_openai_and_are_not_configured(clean_llm_env):
    cfg = LLMConfig.load()

    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.api_key == ""
    assert cfg.model == "gpt-5.4-mini"
    assert cfg.max_tokens == 16384
    assert cfg.is_configured() is False


def test_an_api_key_makes_the_default_endpoint_usable(clean_llm_env):
    assert LLMConfig(api_key="sk-test").is_configured() is True


def test_a_custom_base_url_is_usable_without_any_api_key(clean_llm_env):
    """Local llama.cpp / LM Studio / Ollama endpoints need no credentials."""
    assert LLMConfig(base_url="http://localhost:8080/v1").is_configured() is True


def test_environment_variables_are_applied(clean_llm_env, monkeypatch):
    monkeypatch.setenv("AUTOCUT_LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("AUTOCUT_LLM_API_KEY", "env-key")
    monkeypatch.setenv("AUTOCUT_LLM_MODEL", "env-model")

    cfg = LLMConfig.load()

    assert cfg.base_url == "http://localhost:1234/v1"
    assert cfg.api_key == "env-key"
    assert cfg.model == "env-model"


def test_numeric_environment_variables_are_coerced(clean_llm_env, monkeypatch):
    monkeypatch.setenv("AUTOCUT_LLM_MAX_TOKENS", "2048")
    monkeypatch.setenv("AUTOCUT_LLM_TEMPERATURE", "0.7")

    cfg = LLMConfig.load()

    assert cfg.max_tokens == 2048
    assert isinstance(cfg.max_tokens, int)
    assert cfg.temperature == pytest.approx(0.7)
    assert isinstance(cfg.temperature, float)


def test_config_file_is_read_from_the_llm_section(clean_llm_env, tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm": {"model": "file-model", "api_key": "file-key"}}))
    monkeypatch.setattr(clean_llm_env, "CONFIG_PATH", path)

    cfg = LLMConfig.load()

    assert cfg.model == "file-model"
    assert cfg.api_key == "file-key"


def test_environment_beats_the_config_file(clean_llm_env, tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm": {"model": "file-model"}}))
    monkeypatch.setattr(clean_llm_env, "CONFIG_PATH", path)
    monkeypatch.setenv("AUTOCUT_LLM_MODEL", "env-model")

    assert LLMConfig.load().model == "env-model"


def test_cli_flags_beat_the_environment(clean_llm_env, monkeypatch):
    monkeypatch.setenv("AUTOCUT_LLM_MODEL", "env-model")

    assert LLMConfig.load({"model": "cli-model"}).model == "cli-model"


def test_unset_cli_flags_do_not_clobber_lower_precedence_values(clean_llm_env, monkeypatch):
    """argparse hands over None for every flag the user did not pass."""
    monkeypatch.setenv("AUTOCUT_LLM_MODEL", "env-model")

    cfg = LLMConfig.load({"model": None, "api_key": None, "base_url": None})

    assert cfg.model == "env-model"
    assert cfg.base_url == "https://api.openai.com/v1"


# --------------------------------------------------------------------------
# find_redundancies
# --------------------------------------------------------------------------
def test_unconfigured_llm_is_skipped_without_calling_out(clean_llm_env, monkeypatch):
    def explode(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("no network call may happen when unconfigured")

    monkeypatch.setattr(clean_llm_env, "_chat", explode)

    assert find_redundancies(words(("hi", 0.0, 0.5)), cfg=LLMConfig(), log=lambda *_: None) == []


def _capture_chat(monkeypatch, llm, reply: str) -> list[list[dict]]:
    seen: list[list[dict]] = []

    def fake_chat(cfg, messages):
        seen.append(messages)
        return reply

    monkeypatch.setattr(llm, "_chat", fake_chat)
    return seen


def test_ranges_are_parsed_from_a_plain_json_array(clean_llm_env, monkeypatch):
    _capture_chat(
        monkeypatch,
        clean_llm_env,
        '[{"start": 1.0, "end": 2.5, "reason": "restated"}]',
    )

    out = find_redundancies(
        words(("hi", 0.0, 0.5)), cfg=LLMConfig(api_key="k"), log=lambda *_: None
    )

    assert out == [(1.0, 2.5, "restated")]


def test_json_is_extracted_from_a_markdown_fenced_reply(clean_llm_env, monkeypatch):
    """Models often wrap the array in prose and a ```json fence."""
    reply = 'Sure!\n```json\n[{"start": 3, "end": 4, "reason": "meta"}]\n```\nHope that helps.'
    _capture_chat(monkeypatch, clean_llm_env, reply)

    out = find_redundancies(
        words(("hi", 0.0, 0.5)), cfg=LLMConfig(api_key="k"), log=lambda *_: None
    )

    assert out == [(3.0, 4.0, "meta")]


def test_a_reply_without_a_json_array_is_ignored(clean_llm_env, monkeypatch):
    _capture_chat(monkeypatch, clean_llm_env, "I could not find anything to cut.")

    assert find_redundancies(
        words(("hi", 0.0, 0.5)), cfg=LLMConfig(api_key="k"), log=lambda *_: None
    ) == []


def test_malformed_json_is_ignored_rather_than_raising(clean_llm_env, monkeypatch):
    _capture_chat(monkeypatch, clean_llm_env, '[{"start": 1.0, "end": ]')

    assert find_redundancies(
        words(("hi", 0.0, 0.5)), cfg=LLMConfig(api_key="k"), log=lambda *_: None
    ) == []


def test_unusable_items_are_dropped_but_good_ones_survive(clean_llm_env, monkeypatch):
    _capture_chat(
        monkeypatch,
        clean_llm_env,
        json.dumps(
            [
                {"start": 1.0, "end": 2.0, "reason": "keep me"},
                {"start": 5.0, "end": 5.0, "reason": "zero length"},
                {"start": 9.0, "end": 8.0, "reason": "inverted"},
                {"start": "abc", "end": 3.0, "reason": "not a number"},
                {"end": 3.0, "reason": "no start"},
                "not an object",
            ]
        ),
    )

    out = find_redundancies(
        words(("hi", 0.0, 0.5)), cfg=LLMConfig(api_key="k"), log=lambda *_: None
    )

    assert out == [(1.0, 2.0, "keep me")]


def test_reasons_are_truncated_to_keep_the_plan_readable(clean_llm_env, monkeypatch):
    _capture_chat(
        monkeypatch,
        clean_llm_env,
        json.dumps([{"start": 1.0, "end": 2.0, "reason": "x" * 200}]),
    )

    out = find_redundancies(
        words(("hi", 0.0, 0.5)), cfg=LLMConfig(api_key="k"), log=lambda *_: None
    )

    assert len(out[0][2]) == 80


def test_transcript_is_sent_as_timestamped_sentences(clean_llm_env, monkeypatch):
    """One line per sentence with a leading timestamp — not one word per line."""
    seen = _capture_chat(monkeypatch, clean_llm_env, "[]")

    find_redundancies(
        words(
            ("Hello", 0.0, 0.4),
            ("world.", 0.4, 0.9),
            ("Second", 1.0, 1.4),
            ("sentence!", 1.4, 2.0),
        ),
        cfg=LLMConfig(api_key="k"),
        log=lambda *_: None,
    )

    user_message = seen[0][1]["content"]
    assert "[   0.00] Hello world." in user_message
    assert "[   1.00] Second sentence!" in user_message


def test_a_trailing_fragment_without_punctuation_is_still_sent(clean_llm_env, monkeypatch):
    seen = _capture_chat(monkeypatch, clean_llm_env, "[]")

    find_redundancies(
        words(("dangling", 5.0, 5.5), ("tail", 5.5, 6.0)),
        cfg=LLMConfig(api_key="k"),
        log=lambda *_: None,
    )

    assert "[   5.00] dangling tail" in seen[0][1]["content"]


def test_protected_ranges_are_stated_in_the_prompt(clean_llm_env, monkeypatch):
    seen = _capture_chat(monkeypatch, clean_llm_env, "[]")

    find_redundancies(
        words(("hi", 0.0, 0.5)),
        cfg=LLMConfig(api_key="k"),
        protect_ranges=[(10.0, 20.0)],
        log=lambda *_: None,
    )

    messages = seen[0]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "(10.0, 20.0)" in messages[1]["content"]
