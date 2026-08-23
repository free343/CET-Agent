from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import LearningState, MasteredWord, WordAcquisitionState, WordLevel
from app.services.mastery_service import MasteryService
from app.services.practice_service import PracticeScope, PracticeService
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def test_mastered_word_is_reversible_and_excluded_from_active_routes(
    database,
    word_id,
) -> None:
    service = MasteryService(database)
    update = service.set_mastered(word_id, True)
    assert update.is_mastered is True
    assert service.set_mastered(word_id, True).is_mastered is True

    assert ReviewService(database, WordLevel.CET4).get_new_words(now=NOW) == []
    assert ReviewService(database, WordLevel.CET4).new_count(NOW) == 0
    assert ReviewService(database, WordLevel.CET4).get_due_review_words(now=NOW) == []
    assert (
        PracticeService(database, WordLevel.CET4).get_words(
            PracticeScope.RECENT,
            now=NOW,
        )
        == []
    )
    assert [item.word_id for item in service.list_mastered()] == [word_id]

    restored = service.set_mastered(word_id, False)
    assert restored.is_mastered is False
    assert service.list_mastered() == []
    assert [
        item.word_id for item in ReviewService(database).get_new_words(now=NOW)
    ] == [word_id]


def test_mastery_does_not_change_learning_or_acquisition_state(
    database, word_id
) -> None:
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        state.next_review_at = NOW + timedelta(days=4)
        state.review_count = 2
        state.last_review_at = NOW - timedelta(days=1)
        session.add(
            WordAcquisitionState(
                word_id=word_id,
                proficiency_level=3,
                completed_at=NOW - timedelta(days=2),
            )
        )
        before = (
            state.next_review_at,
            state.review_count,
            state.last_review_at,
        )

    MasteryService(database).set_mastered(word_id, True)
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        acquisition = session.scalar(
            select(WordAcquisitionState).where(WordAcquisitionState.word_id == word_id)
        )
        assert state is not None
        assert acquisition is not None
        assert (
            state.next_review_at,
            state.review_count,
            state.last_review_at,
        ) == before
        assert acquisition.proficiency_level == 3


def test_restoring_mastery_returns_a_learned_word_to_its_original_due_path(
    database, word_id
) -> None:
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        state.next_review_at = NOW - timedelta(hours=1)
        state.review_count = 1
        state.last_review_at = NOW - timedelta(days=2)
        session.add(
            WordAcquisitionState(
                word_id=word_id,
                proficiency_level=3,
                completed_at=NOW - timedelta(days=3),
            )
        )

    mastery = MasteryService(database)
    mastery.set_mastered(word_id, True)
    assert ReviewService(database, WordLevel.CET4).get_due_review_words(now=NOW) == []

    mastery.set_mastered(word_id, False)
    assert [
        item.word_id
        for item in ReviewService(database, WordLevel.CET4).get_due_review_words(
            now=NOW
        )
    ] == [word_id]


def test_mastery_rejects_unknown_word_without_creating_marker(database) -> None:
    with pytest.raises(LookupError):
        MasteryService(database).set_mastered(999_999, True)
    with database.session() as session:
        assert session.scalar(select(MasteredWord.word_id)) is None
