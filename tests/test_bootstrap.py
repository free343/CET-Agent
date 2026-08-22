from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.bootstrap import initialize_database
from app.config import Settings
from app.db.models import StudyLevelActivation, Word, WordLevel


def test_bootstrap_activates_each_selected_level_once(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'bootstrap.db').as_posix()}"
    cet4_settings = Settings(database_url=database_url, study_level="CET4")
    database = initialize_database(cet4_settings)
    try:
        with database.session() as session:
            cet4 = session.get(StudyLevelActivation, WordLevel.CET4)
            assert cet4 is not None
            assert cet4.schedule_rebased is True
            assert cet4.rebased_word_count == 3_320
            original_activation_time = cet4.activated_at
    finally:
        database.dispose()

    database = initialize_database(cet4_settings)
    try:
        with database.session() as session:
            cet4 = session.get(StudyLevelActivation, WordLevel.CET4)
            assert cet4 is not None
            assert cet4.activated_at == original_activation_time
            assert session.scalar(select(func.count(StudyLevelActivation.level))) == 1
    finally:
        database.dispose()

    database = initialize_database(
        Settings(database_url=database_url, study_level="CET6")
    )
    try:
        with database.session() as session:
            cet6 = session.get(StudyLevelActivation, WordLevel.CET6)
            assert cet6 is not None
            assert cet6.schedule_rebased is True
            assert cet6.rebased_word_count == 1_278
            assert session.scalar(select(func.count(StudyLevelActivation.level))) == 2
    finally:
        database.dispose()


def test_concurrent_fresh_bootstrap_converges(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}"
    app_settings = Settings(database_url=database_url, study_level="CET4")
    barrier = Barrier(2)

    def initialize() -> tuple[int, int, int]:
        barrier.wait(timeout=5)
        database = initialize_database(app_settings)
        try:
            with database.session() as session:
                activation = session.get(StudyLevelActivation, WordLevel.CET4)
                assert activation is not None
                return (
                    int(session.scalar(select(func.count(Word.id))) or 0),
                    int(
                        session.scalar(select(func.count(StudyLevelActivation.level)))
                        or 0
                    ),
                    activation.rebased_word_count,
                )
        finally:
            database.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: initialize(), range(2)))

    assert results == [(4_611, 1, 3_320), (4_611, 1, 3_320)]


def test_failed_bootstrap_disposes_database(monkeypatch, tmp_path) -> None:
    class FailingDatabase:
        disposed = False

        @staticmethod
        def upgrade_schema() -> int:
            raise RuntimeError("simulated startup failure")

        def dispose(self) -> None:
            self.disposed = True

    database = FailingDatabase()
    monkeypatch.setattr("app.bootstrap.Database", lambda _url: database)

    with pytest.raises(RuntimeError, match="simulated startup failure"):
        initialize_database(
            Settings(database_url=f"sqlite:///{(tmp_path / 'failure.db').as_posix()}")
        )

    assert database.disposed is True
