from __future__ import annotations

from sqlalchemy import func, select

from app.config import PROJECT_ROOT
from app.db.models import LearningState, Word
from app.db.seed import ensure_learning_states, seed_words


def test_sample_seed_is_idempotent_and_creates_learning_states(database) -> None:
    csv_path = PROJECT_ROOT / "data" / "sample_words.csv"
    with database.session() as session:
        first = seed_words(session, csv_path)
        ensure_learning_states(session)
    with database.session() as session:
        second = seed_words(session, csv_path)
        ensure_learning_states(session)
        word_count = session.scalar(select(func.count(Word.id)))
        state_count = session.scalar(select(func.count(LearningState.id)))

    assert first == 13
    assert second == 0
    assert word_count == 13
    assert state_count == 13
