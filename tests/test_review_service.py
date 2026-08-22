from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.db.models import LearningState, ReviewLog
from app.domain.fsrs_scheduler import Rating
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_submit_review_updates_state_and_creates_log(database, word_id) -> None:
    service = ReviewService(database)
    before = service.get_due_words(now=NOW)
    assert [item.word_id for item in before] == [word_id]

    result = service.submit_review(
        word_id,
        Rating.GOOD,
        1250,
        reviewed_at=NOW,
    )

    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        log_count = session.scalar(select(func.count(ReviewLog.id)))
        assert log_count == 1
        assert state is not None
        assert state.review_count == 1
        assert state.correct_count == 1
        assert state.next_review_at == result.schedule.next_review_at
        assert state.stability == result.schedule.new_stability


def test_again_records_error_and_lapse(database, word_id) -> None:
    ReviewService(database).submit_review(
        word_id,
        Rating.AGAIN,
        800,
        reviewed_at=NOW,
    )
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        assert state.error_count == 1
        assert state.lapse_count == 1


def test_submit_review_rejects_non_monotonic_timestamp(database, word_id) -> None:
    service = ReviewService(database)
    service.submit_review(word_id, Rating.GOOD, 900, reviewed_at=NOW)

    with pytest.raises(ValueError):
        service.submit_review(word_id, Rating.AGAIN, 800, reviewed_at=NOW)

    with database.session() as session:
        assert session.scalar(select(func.count(ReviewLog.id))) == 1


def test_concurrent_review_submissions_do_not_lose_an_update(database, word_id) -> None:
    barrier = Barrier(2)

    def submit_once(_index: int) -> str:
        barrier.wait(timeout=5)
        try:
            ReviewService(database).submit_review(
                word_id,
                Rating.GOOD,
                900,
                reviewed_at=NOW,
            )
            return "saved"
        except ValueError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit_once, range(2)))

    assert sorted(outcomes) == ["saved", "stale"]
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        assert state.review_count == 1
        assert session.scalar(select(func.count(ReviewLog.id))) == 1
