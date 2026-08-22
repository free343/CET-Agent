"""Deterministic adapter around the official FSRS-6 Python implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Protocol

from fsrs import Card, Scheduler
from fsrs import Rating as FSRSRating
from fsrs import State as FSRSState

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
    next_review_at: datetime
    review_count: int
    fsrs_state: int
    fsrs_step: int | None


@dataclass(frozen=True, slots=True)
class ReviewScheduleResult:
    new_difficulty: float
    new_stability: float
    next_review_at: datetime
    scheduled_days: float
    fsrs_state: int
    fsrs_step: int | None


_RATING_MAP = {
    Rating.AGAIN: FSRSRating.Again,
    Rating.HARD: FSRSRating.Hard,
    Rating.GOOD: FSRSRating.Good,
    Rating.EASY: FSRSRating.Easy,
}

# One deterministic ten-minute learning/relearning step preserves the MVP's
# useful short Again interval while letting Good graduate directly to an
# FSRS-computed review interval. Interval fuzzing is disabled so equal history
# always produces equal scheduling output.
_SCHEDULER = Scheduler(
    desired_retention=0.9,
    learning_steps=(timedelta(minutes=10),),
    relearning_steps=(timedelta(minutes=10),),
    maximum_interval=36_500,
    enable_fuzzing=False,
)


def schedule_review(
    state: SchedulerState,
    rating: Rating | int,
    review_time: datetime,
) -> ReviewScheduleResult:
    """Calculate the next official FSRS-6 state without mutating persistence."""
    selected_rating = Rating(rating)
    reviewed_at = ensure_utc(review_time)
    card = _to_fsrs_card(state, reviewed_at)
    updated_card, _review_log = _SCHEDULER.review_card(
        card,
        _RATING_MAP[selected_rating],
        review_datetime=reviewed_at,
    )
    if updated_card.stability is None or updated_card.difficulty is None:
        raise RuntimeError("FSRS did not produce a complete memory state")

    next_review_at = ensure_utc(updated_card.due)
    scheduled_days = (next_review_at - reviewed_at).total_seconds() / 86_400
    if scheduled_days <= 0 or not math.isfinite(scheduled_days):
        raise RuntimeError("FSRS produced an invalid review interval")

    return ReviewScheduleResult(
        new_difficulty=float(updated_card.difficulty),
        new_stability=float(updated_card.stability),
        next_review_at=next_review_at,
        scheduled_days=scheduled_days,
        fsrs_state=int(updated_card.state),
        fsrs_step=updated_card.step,
    )


def _to_fsrs_card(state: SchedulerState, reviewed_at: datetime) -> Card:
    if state.review_count == 0:
        return Card(due=reviewed_at)
    if state.last_review_at is None:
        raise ValueError("Reviewed FSRS state is missing last_review_at")

    stability = float(state.stability)
    difficulty = float(state.difficulty)
    if not math.isfinite(stability) or stability <= 0:
        raise ValueError("FSRS stability must be finite and positive")
    if not math.isfinite(difficulty) or not 1.0 <= difficulty <= 10.0:
        raise ValueError("FSRS difficulty must be finite and within 1..10")

    try:
        card_state = FSRSState(int(state.fsrs_state))
    except ValueError as exc:
        raise ValueError("Unknown persisted FSRS state") from exc
    step = state.fsrs_step
    if step is not None and step < 0:
        raise ValueError("FSRS step cannot be negative")
    if card_state is FSRSState.Review and step is not None:
        raise ValueError("FSRS Review state cannot have a learning step")
    if card_state is not FSRSState.Review and step is None:
        raise ValueError("FSRS learning state requires a step")

    return Card(
        state=card_state,
        step=step,
        stability=stability,
        difficulty=difficulty,
        due=ensure_utc(state.next_review_at),
        last_review=ensure_utc(state.last_review_at),
    )
