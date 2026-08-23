from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AcquisitionAttempt,
    LearningState,
    ReviewLog,
    Word,
    WordAcquisitionState,
    WordLevel,
)
from app.domain.fsrs_scheduler import Rating
from app.services.acquisition_service import AcquisitionService
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _add_choice_words(database, word_id: int) -> list[int]:
    with database.session() as session:
        ids = [word_id]
        for index, (word, meaning) in enumerate(
            (("adopt", "v. 采用"), ("adept", "a. 熟练的"), ("accept", "v. 接受")),
            start=2,
        ):
            row = Word(
                word=word,
                meaning=meaning,
                example=f"We {word} the proposal.",
                level=WordLevel.CET4,
                frequency=100 - index,
            )
            row.learning_state = LearningState(next_review_at=NOW)
            session.add(row)
            session.flush()
            ids.append(row.id)
        return ids


def test_acquisition_progress_is_persisted_without_formal_review_logs(
    database,
    word_id,
) -> None:
    choice_ids = _add_choice_words(database, word_id)
    service = AcquisitionService(database, WordLevel.CET4)
    with database.session() as session:
        initial_learning = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert initial_learning is not None
        initial_fsrs = (
            initial_learning.difficulty,
            initial_learning.stability,
            initial_learning.fsrs_state,
            initial_learning.fsrs_step,
            initial_learning.review_count,
            initial_learning.correct_count,
            initial_learning.error_count,
            initial_learning.lapse_count,
            initial_learning.last_review_at,
        )

    first = service.record_attempt(
        word_id,
        expected_level=0,
        selected_word_id=word_id,
        response_time_ms=100,
        attempted_at=NOW,
    )
    assert (first.level_before, first.level_after, first.is_correct) == (0, 1, True)

    wrong = service.record_attempt(
        word_id,
        expected_level=1,
        selected_word_id=choice_ids[1],
        attempted_at=NOW + timedelta(minutes=1),
    )
    assert (wrong.level_before, wrong.level_after, wrong.is_correct) == (1, 1, False)

    second = service.record_attempt(
        word_id,
        expected_level=1,
        selected_word_id=word_id,
        attempted_at=NOW + timedelta(minutes=2),
    )
    assert (second.level_before, second.level_after) == (1, 2)

    completed = service.record_attempt(
        word_id,
        expected_level=2,
        spelling_answer="  ADAPT ",
        attempted_at=NOW + timedelta(minutes=3),
    )
    assert completed.completed is True
    assert completed.first_review_at == NOW + timedelta(days=1, minutes=3)

    with database.session() as session:
        state = session.scalar(
            select(WordAcquisitionState).where(WordAcquisitionState.word_id == word_id)
        )
        learning = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        assert learning is not None
        assert state.proficiency_level == 3
        assert learning.review_count == 0
        assert (
            learning.difficulty,
            learning.stability,
            learning.fsrs_state,
            learning.fsrs_step,
            learning.review_count,
            learning.correct_count,
            learning.error_count,
            learning.lapse_count,
            learning.last_review_at,
        ) == initial_fsrs
        assert learning.next_review_at == completed.first_review_at
        assert session.scalar(select(func.count(AcquisitionAttempt.id))) == 4
        assert session.scalar(select(func.count(ReviewLog.id))) == 0

    assert word_id not in {
        item.word_id
        for item in AcquisitionService(database, WordLevel.CET4).get_group(now=NOW)
    }
    assert word_id not in {
        item.word_id
        for item in ReviewService(database, WordLevel.CET4).get_new_words(now=NOW)
    }
    assert word_id not in {
        item.word_id
        for item in ReviewService(database, WordLevel.CET4).get_due_review_words(
            now=NOW
        )
    }
    assert word_id in {
        item.word_id
        for item in ReviewService(database, WordLevel.CET4).get_due_review_words(
            now=completed.first_review_at
        )
    }


def test_acquisition_rejects_stale_level_and_mastered_word(database, word_id) -> None:
    service = AcquisitionService(database, WordLevel.CET4)
    service.record_attempt(
        word_id,
        expected_level=0,
        self_confirmed=False,
        selected_word_id=word_id,
        attempted_at=NOW,
    )
    with pytest.raises(ValueError, match="state changed"):
        service.record_attempt(
            word_id,
            expected_level=0,
            selected_word_id=word_id,
            attempted_at=NOW + timedelta(minutes=1),
        )

    from app.services.mastery_service import MasteryService

    MasteryService(database).set_mastered(word_id, True)
    with pytest.raises(ValueError, match="mastered"):
        service.record_attempt(
            word_id,
            expected_level=1,
            selected_word_id=word_id,
            attempted_at=NOW + timedelta(minutes=2),
        )


def test_direct_confirmation_completes_level_two_and_formal_review_starts_later(
    database,
    word_id,
) -> None:
    with database.session() as session:
        session.add(
            WordAcquisitionState(
                word_id=word_id,
                proficiency_level=2,
            )
        )
    result = AcquisitionService(database, WordLevel.CET4).record_attempt(
        word_id,
        expected_level=2,
        self_confirmed=True,
        attempted_at=NOW,
    )
    assert result.self_confirmed is True
    with database.session() as session:
        attempt = session.scalar(select(AcquisitionAttempt))
        assert attempt is not None
        assert attempt.self_confirmed is True
        assert attempt.user_answer == "[self-confirmed]"

    formal = ReviewService(database, WordLevel.CET4).submit_review(
        word_id,
        Rating.GOOD,
        100,
        reviewed_at=NOW + timedelta(days=1, seconds=1),
    )
    assert formal.word_id == word_id


def test_concurrent_attempts_can_advance_only_once(database, word_id) -> None:
    service = AcquisitionService(database, WordLevel.CET4)

    def submit_attempt(offset: int):
        try:
            return service.record_attempt(
                word_id,
                expected_level=0,
                selected_word_id=word_id,
                attempted_at=NOW + timedelta(seconds=offset),
            )
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit_attempt, (0, 1)))

    assert sum(not isinstance(result, ValueError) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    with database.session() as session:
        state = session.scalar(
            select(WordAcquisitionState).where(WordAcquisitionState.word_id == word_id)
        )
        assert state is not None
        assert state.proficiency_level == 1
        assert session.scalar(select(func.count(AcquisitionAttempt.id))) == 1
