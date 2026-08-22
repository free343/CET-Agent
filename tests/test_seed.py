from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.config import PROJECT_ROOT
from app.db.models import LearningState, Word
from app.db.seed import (
    VocabularyDataError,
    ensure_learning_states,
    load_vocabulary_rows,
    seed_words,
)
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)


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


def test_bundled_vocabulary_is_valid_and_seeds_idempotently(database) -> None:
    sources = (
        PROJECT_ROOT / "data" / "sample_words.csv",
        PROJECT_ROOT / "data" / "cet_vocabulary_open.csv",
    )
    with database.session() as session:
        first = sum(seed_words(session, source) for source in sources)
    with database.session() as session:
        second = sum(seed_words(session, source) for source in sources)
        word_count = session.scalar(select(func.count(Word.id)))
        state_count = session.scalar(select(func.count(LearningState.id)))

    assert first == 4_611
    assert second == 0
    assert word_count == 4_611
    assert state_count == 4_611


def test_seed_applies_initial_release_delay(database, tmp_path, monkeypatch) -> None:
    source = tmp_path / "scheduled.csv"
    source.write_text(
        "word,meaning,level,initial_delay_days\n"
        "alpha,阿尔法,CET4,0\n"
        "beta,贝塔,CET4,7\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.db.seed.utc_now", lambda: NOW)

    with database.session() as session:
        assert seed_words(session, source) == 2
    with database.session() as session:
        states = {
            word.word: word.learning_state.next_review_at
            for word in session.scalars(select(Word)).all()
            if word.learning_state is not None
        }

    assert states["alpha"] == NOW
    assert states["beta"] == NOW.replace(day=29)


def test_seed_updates_metadata_without_resetting_learning_state(
    database, tmp_path, monkeypatch
) -> None:
    original = tmp_path / "original.csv"
    original.write_text(
        "word,phonetic,meaning,example,level,frequency\n"
        "adapt,/old/,旧释义,old example,CET6,1\n",
        encoding="utf-8",
    )
    corrected = tmp_path / "corrected.csv"
    corrected.write_text(
        "word,phonetic,meaning,example,level,frequency\n"
        "adapt,/new/,新释义,new example,CET4,99\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.db.seed.utc_now", lambda: NOW)

    with database.session() as session:
        assert seed_words(session, original) == 1
        word = session.scalar(select(Word).where(Word.word == "adapt"))
        assert word is not None and word.learning_state is not None
        original_id = word.id
        word.learning_state.review_count = 5
        word.learning_state.stability = 12.0
        word.learning_state.next_review_at = NOW.replace(day=30)

    with database.session() as session:
        assert seed_words(session, corrected) == 0
    with database.session() as session:
        word = session.scalar(select(Word).where(Word.word == "adapt"))
        assert word is not None and word.learning_state is not None
        assert word.id == original_id
        assert (
            word.phonetic,
            word.meaning,
            word.example,
            word.level.value,
            word.frequency,
        ) == ("/new/", "新释义", "new example", "CET4", 99)
        assert word.learning_state.review_count == 5
        assert word.learning_state.stability == 12.0
        assert word.learning_state.next_review_at == NOW.replace(day=30)


@pytest.mark.parametrize(
    "contents",
    (
        "word,meaning,level\nadapt,适应,CET4\nadapt,改编,CET4\n",
        "word,meaning,level\nadapt,适应,TOEFL\n",
        "word,meaning,level,frequency\nadapt,适应,CET4,-1\n",
    ),
)
def test_vocabulary_loader_rejects_malformed_rows(tmp_path, contents) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text(contents, encoding="utf-8")

    with pytest.raises(VocabularyDataError):
        load_vocabulary_rows(source)
