from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from app.domain.fsrs_scheduler import Rating, ReviewScheduleResult, schedule_review
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


@dataclass
class State:
    difficulty: float = 5.0
    stability: float = 0.4
    last_review_at: datetime | None = None
    next_review_at: datetime = NOW
    review_count: int = 0
    fsrs_state: int = 1
    fsrs_step: int | None = 0


def apply_result(
    state: State, result: ReviewScheduleResult, review_time: datetime
) -> None:
    state.difficulty = result.new_difficulty
    state.stability = result.new_stability
    state.last_review_at = review_time
    state.next_review_at = result.next_review_at
    state.review_count += 1
    state.fsrs_state = result.fsrs_state
    state.fsrs_step = result.fsrs_step


@pytest.mark.parametrize(
    ("rating", "difficulty", "stability", "state_value", "step", "interval"),
    (
        (Rating.AGAIN, 6.4133, 0.212, 1, 0, timedelta(minutes=10)),
        (Rating.HARD, 5.112170705601056, 1.2931, 1, 0, timedelta(minutes=15)),
        (Rating.GOOD, 2.118103970459016, 2.3065, 2, None, timedelta(days=2)),
        (Rating.EASY, 1.0, 8.2956, 2, None, timedelta(days=8)),
    ),
)
def test_fsrs_6_initial_review_reference_vectors(
    rating: Rating,
    difficulty: float,
    stability: float,
    state_value: int,
    step: int | None,
    interval: timedelta,
) -> None:
    result = schedule_review(State(), rating, NOW)

    assert result.new_difficulty == pytest.approx(difficulty)
    assert result.new_stability == pytest.approx(stability)
    assert result.fsrs_state == state_value
    assert result.fsrs_step == step
    assert result.next_review_at == NOW + interval


def test_fsrs_6_multireview_reference_vector() -> None:
    state = State()
    expected = (
        (Rating.GOOD, 2.118103970459016, 2.3065, 2.0),
        (Rating.GOOD, 2.111214235785395, 10.964332335820698, 11.0),
        (Rating.HARD, 4.748284761594571, 32.20330554579487, 32.0),
        (Rating.AGAIN, 8.259025282096594, 2.401075308682949, 10 / 1_440),
        (Rating.GOOD, 8.245994626111335, 2.401075308682949, 2.0),
    )

    review_time = NOW
    for rating, difficulty, stability, interval_days in expected:
        result = schedule_review(state, rating, review_time)
        assert result.new_difficulty == pytest.approx(difficulty, rel=1e-6)
        assert result.new_stability == pytest.approx(stability, rel=1e-6)
        assert result.scheduled_days == pytest.approx(interval_days)
        apply_result(state, result, review_time)
        review_time = result.next_review_at


def test_equal_history_produces_deterministic_interval() -> None:
    state = State(
        difficulty=4.5,
        stability=12.0,
        last_review_at=NOW - timedelta(days=14),
        next_review_at=NOW - timedelta(days=2),
        review_count=5,
        fsrs_state=2,
        fsrs_step=None,
    )
    first = schedule_review(state, Rating.GOOD, NOW)
    second = schedule_review(state, Rating.GOOD, NOW)
    assert first == second


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("stability", float("nan")),
        ("stability", 0.0),
        ("difficulty", float("inf")),
        ("difficulty", 11.0),
        ("fsrs_state", 99),
        ("fsrs_step", -1),
    ),
)
def test_invalid_persisted_memory_state_is_rejected(field: str, value: object) -> None:
    state = State(
        last_review_at=NOW - timedelta(days=2),
        review_count=1,
        fsrs_state=2,
        fsrs_step=None,
    )
    setattr(state, field, value)
    with pytest.raises(ValueError):
        schedule_review(state, Rating.GOOD, NOW)
