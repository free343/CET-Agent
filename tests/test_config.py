from __future__ import annotations

from datetime import time

import pytest

from app.config import Settings


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
    ),
)
def test_settings_reject_unsafe_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Settings(**overrides)
