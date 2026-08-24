from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.db.models import (
    FavoriteWord,
    LearningState,
    MasteredWord,
    PracticeLog,
    ReviewLog,
    Word,
    WordLevel,
)
from app.domain.fsrs_scheduler import Rating
from app.services.practice_service import PracticeScope, PracticeService
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 23, 4, tzinfo=UTC)
SHANGHAI = timezone(timedelta(hours=8))


def _add_word(database, word: str, meaning: str) -> int:
    with database.session() as session:
        row = Word(
            word=word,
            meaning=meaning,
            level=WordLevel.CET4,
            frequency=50,
        )
        row.learning_state = LearningState(next_review_at=NOW - timedelta(days=10))
        session.add(row)
        session.flush()
        return row.id


def _seed_practice_history(database, word_id: int) -> dict[str, int]:
    ids = {
        "yesterday": word_id,
        "recent": _add_word(database, "recentword", "最近词"),
        "wrong": _add_word(database, "wrongword", "错词"),
        "favorite": _add_word(database, "favoriteword", "收藏词"),
    }
    reviews = ReviewService(database, WordLevel.CET4)
    reviews.submit_review(
        ids["favorite"],
        Rating.GOOD,
        500,
        reviewed_at=NOW - timedelta(days=3),
    )
    reviews.submit_review(
        ids["wrong"],
        Rating.AGAIN,
        600,
        reviewed_at=NOW - timedelta(days=2),
    )
    reviews.submit_review(
        ids["yesterday"],
        Rating.GOOD,
        700,
        reviewed_at=NOW - timedelta(days=1),
    )
    reviews.submit_review(
        ids["recent"],
        Rating.GOOD,
        800,
        reviewed_at=NOW - timedelta(hours=1),
    )
    with database.session() as session:
        session.add(FavoriteWord(word_id=ids["favorite"]))
    return ids


def test_practice_scopes_select_only_previously_learned_words(
    database,
    word_id,
) -> None:
    ids = _seed_practice_history(database, word_id)
    service = PracticeService(
        database,
        WordLevel.CET4,
        local_timezone=SHANGHAI,
    )

    assert [
        item.word_id for item in service.get_words(PracticeScope.YESTERDAY, now=NOW)
    ] == [ids["yesterday"]]
    assert [
        item.word_id for item in service.get_words(PracticeScope.RECENT, now=NOW)
    ] == [
        ids["recent"],
        ids["yesterday"],
        ids["wrong"],
        ids["favorite"],
    ]
    assert [
        item.word_id for item in service.get_words(PracticeScope.WRONG, now=NOW)
    ] == [ids["wrong"]]
    assert [
        item.word_id for item in service.get_words(PracticeScope.FAVORITES, now=NOW)
    ] == [ids["favorite"]]

    first_batch = service.get_words(PracticeScope.RECENT, limit=2, now=NOW)
    second_batch = service.get_words(
        PracticeScope.RECENT,
        limit=2,
        now=NOW,
        exclude_word_ids={item.word_id for item in first_batch},
    )
    assert [item.word_id for item in first_batch] == [
        ids["recent"],
        ids["yesterday"],
    ]
    assert [item.word_id for item in second_batch] == [
        ids["wrong"],
        ids["favorite"],
    ]


def test_custom_cluster_queue_preserves_order_and_filters_ineligible_words(
    database,
    word_id,
) -> None:
    ids = _seed_practice_history(database, word_id)
    untouched_id = _add_word(database, "untouchedcluster", "未学习")
    with database.session() as session:
        session.add(MasteredWord(word_id=ids["wrong"]))

    service = PracticeService(database, WordLevel.CET4, local_timezone=SHANGHAI)

    items = service.get_words_by_ids(
        [ids["wrong"], untouched_id, ids["favorite"], ids["favorite"]],
        now=NOW,
    )

    assert [item.word_id for item in items] == [ids["favorite"]]
    with pytest.raises(ValueError, match="explicit word IDs"):
        service.get_words(PracticeScope.CONFUSION_CLUSTER, now=NOW)


def test_custom_cluster_attempt_uses_dedicated_scope(database, word_id) -> None:
    ReviewService(database, WordLevel.CET4).submit_review(
        word_id,
        Rating.GOOD,
        500,
        reviewed_at=NOW - timedelta(hours=1),
    )
    result = PracticeService(database, WordLevel.CET4).record_attempt(
        word_id,
        is_correct=True,
        response_time_ms=100,
        scope=PracticeScope.CONFUSION_CLUSTER,
        practiced_at=NOW,
    )

    assert result.scope is PracticeScope.CONFUSION_CLUSTER
    with database.session() as session:
        practice = session.scalar(select(PracticeLog))
        assert practice is not None
        assert practice.practice_scope == PracticeScope.CONFUSION_CLUSTER.value


def test_practice_attempt_is_logged_without_changing_fsrs(database, word_id) -> None:
    _seed_practice_history(database, word_id)
    service = PracticeService(
        database,
        WordLevel.CET4,
        local_timezone=SHANGHAI,
    )
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        before = (
            state.difficulty,
            state.stability,
            state.last_review_at,
            state.next_review_at,
            state.fsrs_state,
            state.fsrs_step,
            state.review_count,
            state.correct_count,
            state.error_count,
            state.lapse_count,
        )
        review_count = int(session.scalar(select(func.count(ReviewLog.id))) or 0)

    result = service.record_attempt(
        word_id,
        is_correct=False,
        response_time_ms=321,
        scope=PracticeScope.YESTERDAY,
        question_type="meaning_choice_wrong",
        user_answer="错误释义",
        practiced_at=NOW,
    )

    assert result.word_id == word_id
    assert result.is_correct is False
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        after = (
            state.difficulty,
            state.stability,
            state.last_review_at,
            state.next_review_at,
            state.fsrs_state,
            state.fsrs_step,
            state.review_count,
            state.correct_count,
            state.error_count,
            state.lapse_count,
        )
        practice = session.scalar(select(PracticeLog))
        assert practice is not None
        assert practice.practice_scope == PracticeScope.YESTERDAY.value
        assert practice.question_type == "meaning_choice_wrong"
        assert practice.user_answer == "错误释义"
        assert practice.response_time_ms == 321
        assert practice.is_correct is False
        assert session.scalar(select(func.count(ReviewLog.id))) == review_count
    assert after == before


def test_practice_rejects_an_untouched_word(database, word_id) -> None:
    service = PracticeService(database, WordLevel.CET4)

    with pytest.raises(ValueError, match="previously learned"):
        service.record_attempt(
            word_id,
            is_correct=True,
            response_time_ms=100,
            scope=PracticeScope.RECENT,
            practiced_at=NOW,
        )
