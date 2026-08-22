"""A compact FSRS-compatible spaced-repetition scheduler.

The implementation keeps the FSRS concepts of difficulty, stability, and
retrievability without taking a dependency on a specific FSRS package. It is
deliberately isolated so a full FSRS implementation can replace it later.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Protocol

from app.utils.datetime_utils import ensure_utc


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class SchedulerState(Protocol):
    difficulty: float
    stability: float
    last_review_at: datetime | None
    review_count: int


@dataclass(frozen=True, slots=True)
class ReviewScheduleResult:
    new_difficulty: float
    new_stability: float
    next_review_at: datetime
    scheduled_days: float


INITIAL_STABILITY = {
    Rating.AGAIN: 0.10,
    Rating.HARD: 0.80,
    Rating.GOOD: 2.50,
    Rating.EASY: 5.00,
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _difficulty_after_rating(difficulty: float, rating: Rating) -> float:
    # Low ratings make the card harder. A small mean-reversion term prevents
    # difficulty from becoming stuck at an extreme after a few outlier reviews.
    change = {
        Rating.AGAIN: 0.90,
        Rating.HARD: 0.30,
        Rating.GOOD: -0.20,
        Rating.EASY: -0.65,
    }[rating]
    mean_reversion = 0.04 * (5.0 - difficulty)
    return _clamp(difficulty + change + mean_reversion, 1.0, 10.0)


def _retrievability(elapsed_days: float, stability: float) -> float:
    """Estimated recall probability, with stability defined at 90% recall."""
    safe_stability = max(0.1, stability)
    return _clamp(math.exp(math.log(0.9) * elapsed_days / safe_stability), 0.0, 1.0)


def schedule_review(
    state: SchedulerState,
    rating: Rating | int,
    review_time: datetime,
) -> ReviewScheduleResult:
    """Calculate the next schedule without mutating persistence state."""
    selected_rating = Rating(rating)
    reviewed_at = ensure_utc(review_time)
    old_difficulty = _clamp(float(state.difficulty), 1.0, 10.0)
    new_difficulty = _difficulty_after_rating(old_difficulty, selected_rating)

    if state.last_review_at is None or state.review_count == 0:
        new_stability = INITIAL_STABILITY[selected_rating]
    else:
        elapsed = max(
            0.0,
            (reviewed_at - ensure_utc(state.last_review_at)).total_seconds() / 86_400,
        )
        old_stability = max(0.1, float(state.stability))
        recall = _retrievability(elapsed, old_stability)
        if selected_rating is Rating.AGAIN:
            # A lapse sharply reduces stability, while retaining a small amount
            # of prior memory instead of resetting the card completely.
            new_stability = max(0.10, min(1.0, old_stability * 0.35))
        else:
            rating_factor = {
                Rating.HARD: 0.65,
                Rating.GOOD: 1.55,
                Rating.EASY: 2.45,
            }[selected_rating]
            difficulty_factor = (11.0 - new_difficulty) / 10.0
            lateness_factor = max(0.08, 1.0 - recall)
            growth = 1.0 + rating_factor * difficulty_factor * lateness_factor
            if selected_rating is Rating.EASY:
                growth += 0.18
            new_stability = old_stability * growth

    new_stability = round(_clamp(new_stability, 0.10, 36_500.0), 6)
    if selected_rating is Rating.AGAIN:
        scheduled_days = 10.0 / (24 * 60)
    elif selected_rating is Rating.HARD:
        scheduled_days = max(0.5, new_stability * 0.80)
    elif selected_rating is Rating.GOOD:
        scheduled_days = max(1.0, new_stability)
    else:
        scheduled_days = max(2.0, new_stability * 1.30)

    scheduled_days = round(scheduled_days, 6)
    return ReviewScheduleResult(
        new_difficulty=round(new_difficulty, 6),
        new_stability=new_stability,
        next_review_at=reviewed_at + timedelta(days=scheduled_days),
        scheduled_days=scheduled_days,
    )

