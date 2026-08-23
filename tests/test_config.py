from __future__ import annotations

from datetime import time

import pytest

from app.config import (
    Settings,
    _advanced_llm_api_key,
    _env_float,
    _env_int,
    _env_time,
)


@pytest.mark.parametrize(
    "overrides",
    (
        {"confusion_threshold": float("nan")},
        {"confusion_threshold": 1.1},
        {"confusion_window_days": 0},
        {"coerror_window_hours": 0},
        {"max_confusion_candidates": 101},
        {
            "semantic_weight": -1.0,
            "spelling_weight": 1.0,
            "coerror_weight": 1.0,
            "temporal_weight": 0.0,
        },
        {"reminder_start_time": time(23, 0), "reminder_end_time": time(8, 0)},
        {"reminder_cooldown_minutes": 0},
        {"study_level": "TOEFL"},
        {"advanced_llm_provider": "unsupported"},
        {
            "advanced_llm_provider": "ollama",
            "advanced_llm_model": "",
            "advanced_llm_base_url": "",
        },
        {"llm_provider": "unsupported"},
        {"embedding_provider": "unsupported"},
        {"llm_model": ""},
        {"llm_model": "x" * 201},
        {"llm_base_url": "localhost:11434"},
        {"embedding_model": ""},
        {"embedding_base_url": "not-a-url"},
    ),
)
def test_settings_reject_unsafe_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Settings(**overrides)


def test_settings_repr_never_contains_api_keys() -> None:
    value = repr(
        Settings(
            llm_api_key="local-secret-sentinel",
            advanced_llm_api_key="advanced-secret-sentinel",
        )
    )

    assert "local-secret-sentinel" not in value
    assert "advanced-secret-sentinel" not in value


def test_official_deepseek_advanced_channel_reuses_deepseek_key(monkeypatch) -> None:
    monkeypatch.setenv("ADVANCED_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("ADVANCED_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.delenv("ADVANCED_LLM_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "shared-secret-sentinel")

    assert _advanced_llm_api_key() == "shared-secret-sentinel"

    monkeypatch.setenv("ADVANCED_LLM_BASE_URL", "https://models.example")
    assert _advanced_llm_api_key() is None


def test_official_deepseek_advanced_channel_requires_a_key() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        Settings(
            advanced_llm_provider="openai-compatible",
            advanced_llm_model="deepseek-v4-flash",
            advanced_llm_base_url="https://api.deepseek.com",
            advanced_llm_api_key=None,
        )


@pytest.mark.parametrize(
    ("name", "raw_value", "reader"),
    (
        ("TEST_FLOAT", "not-a-float", lambda: _env_float("TEST_FLOAT", 1.0)),
        ("TEST_INT", "1.5", lambda: _env_int("TEST_INT", 1)),
        ("TEST_TIME", "25:00", lambda: _env_time("TEST_TIME", "08:00")),
    ),
)
def test_malformed_environment_values_fail_fast(
    monkeypatch, name: str, raw_value: str, reader
) -> None:
    monkeypatch.setenv(name, raw_value)

    with pytest.raises(ValueError, match=name):
        reader()
