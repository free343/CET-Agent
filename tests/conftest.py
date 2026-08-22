from __future__ import annotations

from datetime import datetime

import pytest

from app.db.database import Database
from app.db.models import LearningState, Word, WordLevel
from app.utils.datetime_utils import UTC


@pytest.fixture
def database(tmp_path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    db.create_tables()
    yield db
    db.dispose()


@pytest.fixture
def word_id(database: Database) -> int:
    with database.session() as session:
        word = Word(
            word="adapt",
            phonetic="/əˈdæpt/",
            meaning="适应；改编",
            example="Students adapt quickly.",
            level=WordLevel.CET4,
            frequency=100,
        )
        word.learning_state = LearningState(
            next_review_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        session.add(word)
        session.flush()
        return word.id

