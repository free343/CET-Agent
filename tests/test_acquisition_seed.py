from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.acquisition_seed import ensure_acquisition_states
from app.db.models import (
    LearningState,
    ReviewLog,
    Word,
    WordAcquisitionState,
    WordLevel,
)
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def test_acquisition_seed_adopts_real_history_but_not_demo_evidence(database) -> None:
    with database.session() as session:
        untouched = Word(word="untouched", meaning="未学习", level=WordLevel.CET4)
        untouched.learning_state = LearningState(next_review_at=NOW)
        learned = Word(word="learned", meaning="已学习", level=WordLevel.CET4)
        learned.learning_state = LearningState(
            next_review_at=NOW + timedelta(days=2),
            review_count=1,
            last_review_at=NOW - timedelta(days=1),
        )
        demo = Word(word="demo", meaning="演示", level=WordLevel.CET4)
        demo.learning_state = LearningState(next_review_at=NOW)
        session.add_all((untouched, learned, demo))
        session.flush()
        session.add(
            ReviewLog(
                word_id=demo.id,
                reviewed_at=NOW - timedelta(days=1),
                rating=1,
                is_correct=False,
                response_time_ms=0,
                question_type="demo_confusion",
                previous_stability=0.4,
                new_stability=0.4,
                previous_difficulty=5.0,
                new_difficulty=5.0,
                scheduled_days=0,
            )
        )

    assert ensure_acquisition_states_in_session(database) == 3
    with database.session() as session:
        states = {
            word.word: state.proficiency_level
            for word, state in session.execute(
                select(Word, WordAcquisitionState).join(
                    WordAcquisitionState,
                    WordAcquisitionState.word_id == Word.id,
                )
            ).all()
        }
        assert states == {"untouched": 0, "learned": 3, "demo": 0}
    assert ensure_acquisition_states_in_session(database) == 0


def ensure_acquisition_states_in_session(database) -> int:
    with database.session() as session:
        return ensure_acquisition_states(session)
