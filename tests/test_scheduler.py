from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.fsrs_scheduler import Rating, schedule_review
from app.utils.datetime_utils import UTC


@dataclass
class State:
    difficulty: float = 5.0
    stability: float = 2.0
    last_review_at: datetime | None = None
    review_count: int = 0


NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_good_schedules_after_current_time() -> None:
    result = schedule_review(State(), Rating.GOOD, NOW)
    assert result.next_review_at > NOW
    assert result.scheduled_days >= 1.0


def test_again_interval_is_much_shorter_than_good() -> None:
    state = State(last_review_at=NOW - timedelta(days=2), review_count=1)
    again = schedule_review(state, Rating.AGAIN, NOW)
    good = schedule_review(state, Rating.GOOD, NOW)
    assert again.scheduled_days < good.scheduled_days / 10


def test_repeated_easy_increases_stability() -> None:
    state = State()
    first = schedule_review(state, Rating.EASY, NOW)
    state.stability = first.new_stability
    state.last_review_at = first.next_review_at
    state.review_count = 1
    second = schedule_review(state, Rating.EASY, first.next_review_at)
    assert second.new_stability > first.new_stability

