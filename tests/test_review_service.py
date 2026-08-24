from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.domain.fsrs_scheduler import Rating
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_workload_defaults_are_overridable_without_touching_review_state(
    database,
) -> None:
    service = ReviewService(
        database,
        WordLevel.CET4,
        extra_study_limit=3,
    )

    assert service.extra_study_limit == 3


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
        assert state.fsrs_state == result.schedule.fsrs_state
        assert state.fsrs_step == result.schedule.fsrs_step


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


@pytest.mark.parametrize("rating", [Rating.AGAIN, Rating.GOOD])
def test_undo_review_restores_full_previous_state_and_deletes_log(
    database,
    word_id,
    rating,
) -> None:
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        state.difficulty = 6.2
        state.stability = 3.4
        state.last_review_at = NOW - timedelta(days=2)
        state.next_review_at = NOW - timedelta(hours=1)
        state.review_count = 4
        state.correct_count = 3
        state.error_count = 1
        state.lapse_count = 1
        state.fsrs_state = 2
        state.fsrs_step = None

    submission = ReviewService(database).submit_review(
        word_id,
        rating,
        850,
        reviewed_at=NOW,
    )
    result = ReviewService(database).undo_review(submission.review_log_id)

    assert result.review_log_id == submission.review_log_id
    assert result.word_id == word_id
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        assert state.difficulty == pytest.approx(6.2)
        assert state.stability == pytest.approx(3.4)
        assert state.last_review_at == NOW - timedelta(days=2)
        assert state.next_review_at == NOW - timedelta(hours=1)
        assert state.review_count == 4
        assert state.correct_count == 3
        assert state.error_count == 1
        assert state.lapse_count == 1
        assert state.fsrs_state == 2
        assert state.fsrs_step is None
        assert session.get(ReviewLog, submission.review_log_id) is None


def test_undo_review_rejects_a_log_when_card_has_a_later_review(
    database,
    word_id,
) -> None:
    service = ReviewService(database)
    first = service.submit_review(
        word_id,
        Rating.GOOD,
        900,
        reviewed_at=NOW,
    )
    second = service.submit_review(
        word_id,
        Rating.HARD,
        950,
        reviewed_at=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="latest"):
        service.undo_review(first.review_log_id)

    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        assert state.review_count == 2
        assert session.get(ReviewLog, second.review_log_id) is not None
        assert session.get(ReviewLog, first.review_log_id) is not None


def test_review_queue_and_count_are_filtered_by_study_level(database, word_id) -> None:
    with database.session() as session:
        cet6_word = Word(word="adept", meaning="熟练的", level=WordLevel.CET6)
        cet6_word.learning_state = LearningState(next_review_at=NOW)
        session.add(cet6_word)

    cet4 = ReviewService(database, WordLevel.CET4)
    cet6 = ReviewService(database, WordLevel.CET6)

    assert [item.word for item in cet4.get_due_words(now=NOW)] == ["adapt"]
    assert [item.word for item in cet6.get_due_words(now=NOW)] == ["adept"]
    assert cet4.due_count(NOW) == 1
    assert cet6.due_count(NOW) == 1
    assert ReviewService(database).due_count(NOW) == 2


def test_new_and_due_review_queues_are_disjoint(database, word_id) -> None:
    with database.session() as session:
        learned_due = Word(
            word="reviewdue",
            meaning="到期复习词",
            level=WordLevel.CET4,
            frequency=90,
        )
        learned_due.learning_state = LearningState(
            next_review_at=NOW - timedelta(hours=1),
            last_review_at=NOW - timedelta(days=2),
            review_count=1,
            correct_count=1,
            fsrs_state=2,
            fsrs_step=None,
        )
        learned_future = Word(
            word="reviewfuture",
            meaning="未来复习词",
            level=WordLevel.CET4,
            frequency=80,
        )
        learned_future.learning_state = LearningState(
            next_review_at=NOW + timedelta(days=1),
            last_review_at=NOW - timedelta(days=1),
            review_count=1,
            correct_count=1,
            fsrs_state=2,
            fsrs_step=None,
        )
        session.add_all((learned_due, learned_future))

    service = ReviewService(database, WordLevel.CET4)

    assert [item.word for item in service.get_new_words(now=NOW)] == ["adapt"]
    assert [item.word for item in service.get_due_review_words(now=NOW)] == [
        "reviewdue"
    ]
    assert service.new_count(NOW) == 1
    assert service.due_review_count(NOW) == 1
    assert {item.word for item in service.get_due_words(now=NOW)} == {
        "adapt",
        "reviewdue",
    }


def test_due_word_includes_four_deterministic_meaning_options(
    database, word_id
) -> None:
    with database.session() as session:
        for index, meaning in enumerate(("采用", "状态", "补充"), start=1):
            word = Word(
                word=f"choiceword{index}",
                meaning=meaning,
                level=WordLevel.CET4,
                frequency=100 - index,
            )
            word.learning_state = LearningState(
                next_review_at=NOW.replace(year=NOW.year + 1)
            )
            session.add(word)

    first = ReviewService(database, WordLevel.CET4).get_due_words(now=NOW)[0]
    second = ReviewService(database, WordLevel.CET4).get_due_words(now=NOW)[0]

    assert first.meaning_options == second.meaning_options
    assert len(first.meaning_options) == 4
    assert sum(option.word_id == word_id for option in first.meaning_options) == 1


def test_extra_study_unlocks_only_untouched_selected_level(database) -> None:
    with database.session() as session:
        for index in range(7):
            word = Word(
                word=f"futurecet4{index}",
                meaning=f"未来四级词 {index}",
                level=WordLevel.CET4,
                frequency=100 - index,
            )
            word.learning_state = LearningState(
                next_review_at=NOW.replace(day=NOW.day + 1 + index)
            )
            session.add(word)
        cet6 = Word(word="futurecet6", meaning="未来六级词", level=WordLevel.CET6)
        cet6.learning_state = LearningState(
            next_review_at=NOW.replace(month=NOW.month + 1)
        )
        session.add(cet6)
        learned = Word(word="learnedfuture", meaning="已学词", level=WordLevel.CET4)
        learned.learning_state = LearningState(
            next_review_at=NOW.replace(month=NOW.month + 1),
            review_count=1,
            last_review_at=NOW.replace(day=NOW.day - 1),
        )
        session.add(learned)

    service = ReviewService(database, WordLevel.CET4)
    first = service.unlock_extra_words(5, NOW)

    assert first.unlocked_count == 5
    assert first.remaining_count == 2
    for item in service.get_due_words(now=NOW):
        service.submit_review(
            item.word_id,
            Rating.GOOD,
            900,
            reviewed_at=NOW + timedelta(seconds=1),
        )
    second = service.unlock_extra_words(5, NOW + timedelta(seconds=2))

    assert second.unlocked_count == 2
    assert second.remaining_count == 0
    assert len(service.get_due_words(now=NOW + timedelta(seconds=2))) == 2
    assert ReviewService(database, WordLevel.CET6).due_count(NOW) == 0


def test_extra_study_requires_explicit_level(database) -> None:
    with pytest.raises(ValueError):
        ReviewService(database).unlock_extra_words(now=NOW)


def test_extra_study_preserves_newly_due_priority(database, word_id) -> None:
    with database.session() as session:
        future = Word(word="future", meaning="未来", level=WordLevel.CET4)
        future.learning_state = LearningState(
            next_review_at=NOW.replace(month=NOW.month + 1)
        )
        session.add(future)

    result = ReviewService(database, WordLevel.CET4).unlock_extra_words(5, NOW)

    assert result.unlocked_count == 0
    assert result.remaining_count == 1
    assert result.due_count == 1


def test_extra_new_words_are_not_blocked_by_the_separate_review_route(
    database,
    word_id,
) -> None:
    with database.session() as session:
        learned_state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert learned_state is not None
        learned_state.review_count = 1
        learned_state.correct_count = 1
        learned_state.last_review_at = NOW - timedelta(days=2)
        learned_state.fsrs_state = 2
        learned_state.fsrs_step = None
        future = Word(word="separatefuture", meaning="未来新词", level=WordLevel.CET4)
        future.learning_state = LearningState(next_review_at=NOW + timedelta(days=1))
        session.add(future)

    result = ReviewService(database, WordLevel.CET4).unlock_extra_words(5, NOW)

    assert result.due_count == 0
    assert result.unlocked_count == 1
    assert [
        item.word
        for item in ReviewService(database, WordLevel.CET4).get_new_words(now=NOW)
    ] == ["separatefuture"]


def test_extra_study_rejects_nonpositive_limit(database) -> None:
    with pytest.raises(ValueError):
        ReviewService(database, WordLevel.CET4).unlock_extra_words(0, NOW)


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
