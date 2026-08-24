from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.db.models import (
    LearningState,
    ReviewLog,
    StudyLevelActivation,
    Word,
    WordLevel,
)
from app.db.seed import VocabularySeedRow
from app.db.study_level_activation import activate_study_level
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
OLD_DUE = NOW - timedelta(days=90)


def _row(word: str, level: WordLevel, delay: int) -> VocabularySeedRow:
    return VocabularySeedRow(
        word=word,
        phonetic="",
        meaning=word,
        example="",
        level=level,
        frequency=1,
        initial_delay_days=delay,
    )


def _add_word(session, word: str, level: WordLevel) -> Word:
    item = Word(word=word, meaning=word, level=level)
    item.learning_state = LearningState(next_review_at=OLD_DUE)
    session.add(item)
    session.flush()
    return item


def _review_log(word_id: int, reviewed_at: datetime) -> ReviewLog:
    return ReviewLog(
        word_id=word_id,
        reviewed_at=reviewed_at,
        rating=3,
        is_correct=True,
        response_time_ms=500,
        previous_stability=1.0,
        new_stability=2.0,
        previous_difficulty=5.0,
        new_difficulty=4.9,
        scheduled_days=1.0,
    )


def test_first_activation_rebases_only_untouched_open_words(database) -> None:
    open_rows = (
        _row("alpha", WordLevel.CET6, 0),
        _row("beta", WordLevel.CET6, 7),
        _row("other", WordLevel.CET4, 3),
    )
    with database.session() as session:
        _add_word(session, "alpha", WordLevel.CET6)
        _add_word(session, "beta", WordLevel.CET6)
        curated = _add_word(session, "curated", WordLevel.CET6)
        assert curated.learning_state is not None
        curated.learning_state.review_count = 1
        curated.learning_state.last_review_at = NOW - timedelta(days=10)
        session.add(_review_log(curated.id, NOW - timedelta(days=10)))
        _add_word(session, "other", WordLevel.CET4)

    with database.session() as session:
        result = activate_study_level(
            session,
            WordLevel.CET6,
            open_rows,
            activated_at=NOW,
        )

    assert result.newly_activated is True
    assert result.schedule_rebased is True
    assert result.rebased_word_count == 2
    with database.session() as session:
        due_times = {
            word.word: word.learning_state.next_review_at
            for word in session.scalars(select(Word)).all()
            if word.learning_state is not None
        }
        activation = session.get(StudyLevelActivation, WordLevel.CET6)
        assert activation is not None
        assert activation.activated_at == NOW
        assert activation.rebased_word_count == 2

    assert due_times["alpha"] == NOW
    assert due_times["beta"] == NOW + timedelta(days=7)
    assert due_times["curated"] == OLD_DUE
    assert due_times["other"] == OLD_DUE

    with database.session() as session:
        repeated = activate_study_level(
            session,
            WordLevel.CET6,
            open_rows,
            activated_at=NOW + timedelta(days=30),
        )
    assert repeated.newly_activated is False
    assert repeated.rebased_word_count == 0
    with database.session() as session:
        beta = session.scalar(select(Word).where(Word.word == "beta"))
        assert beta is not None and beta.learning_state is not None
        assert beta.learning_state.next_review_at == NOW + timedelta(days=7)


def test_level_with_review_history_is_adopted_without_rebasing(database) -> None:
    reviewed_at = NOW - timedelta(days=30)
    with database.session() as session:
        learned = _add_word(session, "learned", WordLevel.CET4)
        untouched = _add_word(session, "untouched", WordLevel.CET4)
        assert learned.learning_state is not None
        learned.learning_state.review_count = 1
        learned.learning_state.last_review_at = reviewed_at
        learned.learning_state.next_review_at = NOW + timedelta(days=2)
        session.add(_review_log(learned.id, reviewed_at))
        untouched_due = untouched.learning_state.next_review_at

    open_rows = (
        _row("learned", WordLevel.CET4, 0),
        _row("untouched", WordLevel.CET4, 10),
    )
    with database.session() as session:
        result = activate_study_level(
            session,
            WordLevel.CET4,
            open_rows,
            activated_at=NOW,
        )

    assert result.newly_activated is True
    assert result.schedule_rebased is False
    assert result.rebased_word_count == 0
    assert result.activated_at == reviewed_at
    with database.session() as session:
        untouched = session.scalar(select(Word).where(Word.word == "untouched"))
        assert untouched is not None and untouched.learning_state is not None
        assert untouched.learning_state.next_review_at == untouched_due
        assert session.scalar(select(func.count(StudyLevelActivation.level))) == 1


def test_explicit_daily_limit_rebases_in_frequency_order(database) -> None:
    open_rows = (
        VocabularySeedRow(
            word="beta",
            phonetic="",
            meaning="beta",
            example="",
            level=WordLevel.CET6,
            frequency=10,
            initial_delay_days=0,
        ),
        VocabularySeedRow(
            word="alpha",
            phonetic="",
            meaning="alpha",
            example="",
            level=WordLevel.CET6,
            frequency=20,
            initial_delay_days=0,
        ),
    )
    with database.session() as session:
        _add_word(session, "alpha", WordLevel.CET6)
        _add_word(session, "beta", WordLevel.CET6)
        activate_study_level(
            session,
            WordLevel.CET6,
            open_rows,
            activated_at=NOW,
            daily_new_word_limit=1,
        )

    with database.session() as session:
        alpha = session.scalar(select(Word).where(Word.word == "alpha"))
        beta = session.scalar(select(Word).where(Word.word == "beta"))
        assert alpha is not None and alpha.learning_state is not None
        assert beta is not None and beta.learning_state is not None
        assert alpha.learning_state.next_review_at == NOW
        assert beta.learning_state.next_review_at == NOW + timedelta(days=1)
