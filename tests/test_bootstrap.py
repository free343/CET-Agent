from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app import bootstrap
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


def test_runtime_config_template_is_installed_without_overwrite(
    monkeypatch,
    tmp_path,
) -> None:
    resource_root = tmp_path / "resources"
    runtime_root = tmp_path / "runtime"
    resource_root.mkdir()
    (resource_root / ".env.example").write_text("STUDY_LEVEL=CET4\n", encoding="utf-8")
    target = runtime_root / ".env.example"
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", resource_root)
    monkeypatch.setattr(bootstrap, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(bootstrap, "ENV_FILE", runtime_root / ".env")

    bootstrap._install_runtime_config_template()
    assert target.read_text(encoding="utf-8") == "STUDY_LEVEL=CET4\n"

    target.write_text("user-owned\n", encoding="utf-8")
    bootstrap._install_runtime_config_template()
    assert target.read_text(encoding="utf-8") == "user-owned\n"


def test_bootstrap_disposes_database_when_learning_aids_are_malformed(
    monkeypatch,
    tmp_path,
) -> None:
    from app.db.learning_aid_seed import LearningAidDataError

    disposed = {"done": False}

    class TrackingDatabase:
        def __init__(self, _url) -> None:
            pass

        @staticmethod
        def upgrade_schema() -> int:
            return 8

        @staticmethod
        def session():
            raise AssertionError("session must not open before aid validation")

        def dispose(self) -> None:
            disposed["done"] = True

    monkeypatch.setattr("app.bootstrap.Database", lambda _url: TrackingDatabase(_url))
    monkeypatch.setattr(
        "app.bootstrap.load_learning_aid_records",
        lambda _path: (_ for _ in ()).throw(LearningAidDataError("malformed aids")),
    )

    with pytest.raises(LearningAidDataError):
        initialize_database(
            Settings(database_url=f"sqlite:///{(tmp_path / 'failure.db').as_posix()}")
        )

    assert disposed["done"] is True
