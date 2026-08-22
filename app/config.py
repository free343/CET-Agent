"""Environment-backed application configuration."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_time(name: str, default: str) -> time:
    raw = os.getenv(name, default)
    try:
        hours, minutes = (int(part) for part in raw.split(":", maxsplit=1))
        return time(hours, minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must use HH:MM in 24-hour time") from exc


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
    study_level: str = os.getenv("STUDY_LEVEL", "CET4").strip().upper()
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:3b")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434")
    llm_api_key: str | None = field(
        default=os.getenv("LLM_API_KEY") or None,
        repr=False,
    )
    advanced_llm_provider: str = os.getenv("ADVANCED_LLM_PROVIDER", "").strip()
    advanced_llm_model: str = os.getenv("ADVANCED_LLM_MODEL", "").strip()
    advanced_llm_base_url: str = os.getenv("ADVANCED_LLM_BASE_URL", "").strip()
    advanced_llm_api_key: str | None = field(
        default=os.getenv("ADVANCED_LLM_API_KEY") or None,
        repr=False,
    )
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
        if self.study_level not in {"CET4", "CET6"}:
            raise ValueError("STUDY_LEVEL must be CET4 or CET6")
        local_provider = self.llm_provider.strip().lower().replace("_", "-")
        if local_provider not in {"ollama", "openai-compatible"}:
            raise ValueError("LLM_PROVIDER is unsupported")
        embedding_provider = self.embedding_provider.strip().lower()
        if embedding_provider != "ollama":
            raise ValueError("EMBEDDING_PROVIDER is unsupported")
        _validate_model_endpoint("LLM", self.llm_model, self.llm_base_url)
        _validate_model_endpoint(
            "EMBEDDING",
            self.embedding_model,
            self.embedding_base_url,
        )
        advanced_provider = self.advanced_llm_provider.lower().replace("_", "-")
        if advanced_provider not in {"", "ollama", "openai-compatible"}:
            raise ValueError("ADVANCED_LLM_PROVIDER is unsupported")
        if advanced_provider and not (
            self.advanced_llm_model and self.advanced_llm_base_url
        ):
            raise ValueError(
                "ADVANCED_LLM_MODEL and ADVANCED_LLM_BASE_URL are required when "
                "ADVANCED_LLM_PROVIDER is enabled"
            )
        if advanced_provider:
            _validate_model_endpoint(
                "ADVANCED_LLM",
                self.advanced_llm_model,
                self.advanced_llm_base_url,
            )
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
            raise ValueError(
                "Confusion relation weights must be finite and non-negative"
            )
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-6):
            raise ValueError("Confusion relation weights must sum to 1.0")
        if self.reminder_start_time >= self.reminder_end_time:
            raise ValueError(
                "REMINDER_START_TIME must be earlier than REMINDER_END_TIME"
            )
        if self.reminder_cooldown_minutes <= 0:
            raise ValueError("REMINDER_COOLDOWN_MINUTES must be greater than 0")


def _validate_model_endpoint(prefix: str, model: str, base_url: str) -> None:
    normalized_model = model.strip()
    if not normalized_model:
        raise ValueError(f"{prefix}_MODEL must not be empty")
    if len(normalized_model) > 200:
        raise ValueError(f"{prefix}_MODEL must not exceed 200 characters")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{prefix}_BASE_URL must be an absolute HTTP(S) URL")


settings = Settings()
