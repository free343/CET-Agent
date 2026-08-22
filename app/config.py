"""Environment-backed application configuration."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_time(name: str, default: str) -> time:
    raw = os.getenv(name, default)
    try:
        hours, minutes = (int(part) for part in raw.split(":", maxsplit=1))
        return time(hours, minutes)
    except (TypeError, ValueError):
        fallback_hours, fallback_minutes = (int(part) for part in default.split(":"))
        return time(fallback_hours, fallback_minutes)


def _database_url() -> str:
    raw = os.getenv("DATABASE_URL", "sqlite:///data/cet_agent.db")
    if raw.startswith("sqlite:///"):
        db_path = Path(raw.removeprefix("sqlite:///"))
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        return f"sqlite:///{db_path.as_posix()}"
    return raw


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = _database_url()
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:3b")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434")
    llm_api_key: str | None = os.getenv("LLM_API_KEY") or None
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "ollama")
    embedding_base_url: str = os.getenv(
        "EMBEDDING_BASE_URL",
        "http://127.0.0.1:11434",
    )
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

    confusion_threshold: float = _env_float("CONFUSION_THRESHOLD", 0.65)
    confusion_window_days: int = _env_int("CONFUSION_WINDOW_DAYS", 30)
    coerror_window_hours: int = _env_int("COERROR_WINDOW_HOURS", 24)
    max_confusion_candidates: int = _env_int("MAX_CONFUSION_CANDIDATES", 100)

    semantic_weight: float = _env_float("SEMANTIC_WEIGHT", 0.30)
    spelling_weight: float = _env_float("SPELLING_WEIGHT", 0.25)
    coerror_weight: float = _env_float("COERROR_WEIGHT", 0.30)
    temporal_weight: float = _env_float("TEMPORAL_WEIGHT", 0.15)

    reminder_start_time: time = field(
        default_factory=lambda: _env_time("REMINDER_START_TIME", "08:00")
    )
    reminder_end_time: time = field(
        default_factory=lambda: _env_time("REMINDER_END_TIME", "23:00")
    )
    reminder_cooldown_minutes: int = _env_int("REMINDER_COOLDOWN_MINUTES", 30)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def __post_init__(self) -> None:
        if not math.isfinite(self.confusion_threshold) or not (
            0.0 <= self.confusion_threshold <= 1.0
        ):
            raise ValueError("CONFUSION_THRESHOLD must be between 0 and 1")
        if self.confusion_window_days <= 0:
            raise ValueError("CONFUSION_WINDOW_DAYS must be greater than 0")
        if self.coerror_window_hours <= 0:
            raise ValueError("COERROR_WINDOW_HOURS must be greater than 0")
        if not 1 <= self.max_confusion_candidates <= 100:
            raise ValueError("MAX_CONFUSION_CANDIDATES must be between 1 and 100")

        weights = (
            self.semantic_weight,
            self.spelling_weight,
            self.coerror_weight,
            self.temporal_weight,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in weights):
            raise ValueError("Confusion relation weights must be finite and non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-6):
            raise ValueError("Confusion relation weights must sum to 1.0")
        if self.reminder_start_time >= self.reminder_end_time:
            raise ValueError("REMINDER_START_TIME must be earlier than REMINDER_END_TIME")
        if self.reminder_cooldown_minutes <= 0:
            raise ValueError("REMINDER_COOLDOWN_MINUTES must be greater than 0")


settings = Settings()
