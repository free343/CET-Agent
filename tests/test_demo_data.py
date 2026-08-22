from __future__ import annotations

from sqlalchemy import select

from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.utils.datetime_utils import utc_now
from scripts import create_demo_data


def test_demo_history_does_not_mutate_fsrs_learning_state(
    database,
    monkeypatch,
) -> None:
    with database.session() as session:
        for group in create_demo_data.GROUPS:
            for word_text in group:
                session.add(
                    Word(
                        word=word_text,
                        meaning=f"{word_text} meaning",
                        level=WordLevel.CET4,
                        learning_state=LearningState(next_review_at=utc_now()),
                    )
                )

    monkeypatch.setattr(create_demo_data, "initialize_database", lambda: database)

    create_demo_data.create_demo_data()

    with database.session() as session:
        states = session.scalars(select(LearningState)).all()
        demo_logs = session.scalars(
            select(ReviewLog).where(ReviewLog.question_type == "demo_confusion")
        ).all()
        assert len(demo_logs) == 28
        assert all(state.review_count == 0 for state in states)
        assert all(state.error_count == 0 for state in states)
        assert all(state.lapse_count == 0 for state in states)
        assert all(state.last_review_at is None for state in states)
