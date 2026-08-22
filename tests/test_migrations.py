from __future__ import annotations

import pytest
from sqlalchemy import inspect, select, text

from app.db.database import Database
from app.db.migrations import (
    CURRENT_SCHEMA_VERSION,
    SchemaMigrationError,
    upgrade_schema,
)
from app.db.models import Base, Word, WordLevel


def make_database(tmp_path, name: str = "migration.db") -> Database:
    return Database(f"sqlite:///{(tmp_path / name).as_posix()}")


def read_schema_version(database: Database) -> int:
    with database.engine.connect() as connection:
        return connection.execute(
            text("SELECT version FROM schema_version WHERE id = 1")
        ).scalar_one()


def test_fresh_database_upgrades_to_current_version_idempotently(tmp_path) -> None:
    database = make_database(tmp_path)
    try:
        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION
        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        table_names = set(inspect(database.engine).get_table_names())
        assert "words" in table_names
        assert "schema_version" in table_names
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_unversioned_mvp_database_is_adopted_without_data_loss(tmp_path) -> None:
    database = make_database(tmp_path)
    try:
        Base.metadata.create_all(database.engine)
        with database.session() as session:
            session.add(
                Word(
                    word="legacy",
                    meaning="旧版数据",
                    level=WordLevel.CET4,
                )
            )

        assert "schema_version" not in inspect(database.engine).get_table_names()
        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        with database.session() as session:
            assert session.scalar(select(Word.word)) == "legacy"
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_version_one_database_adds_fsrs_state_without_data_loss(tmp_path) -> None:
    database = make_database(tmp_path)
    try:
        with database.engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE schema_version (
                    id INTEGER PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "INSERT INTO schema_version (id, version) VALUES (1, 1)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE learning_states (
                    id INTEGER PRIMARY KEY,
                    review_count INTEGER NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "INSERT INTO learning_states (id, review_count) VALUES (1, 0), (2, 3)"
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION
        with database.engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT id, review_count, fsrs_state, fsrs_step "
                "FROM learning_states ORDER BY id"
            ).all()
        assert rows == [(1, 0, 1, 0), (2, 3, 2, None)]
    finally:
        database.dispose()


def test_version_two_database_adds_level_activation_table(tmp_path) -> None:
    database = make_database(tmp_path)
    try:
        with database.engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE schema_version (
                    id INTEGER PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "INSERT INTO schema_version (id, version) VALUES (1, 2)"
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION
        assert "study_level_activations" in inspect(database.engine).get_table_names()
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_version_three_database_adds_reminder_review_leases(tmp_path) -> None:
    database = make_database(tmp_path)
    try:
        with database.engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE schema_version (
                    id INTEGER PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "INSERT INTO schema_version (id, version) VALUES (1, 3)"
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION
        assert "reminder_review_leases" in inspect(database.engine).get_table_names()
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_newer_database_version_is_rejected(tmp_path) -> None:
    database = make_database(tmp_path)
    try:
        database.upgrade_schema()
        future_version = CURRENT_SCHEMA_VERSION + 1
        with database.engine.begin() as connection:
            connection.execute(
                text("UPDATE schema_version SET version = :version WHERE id = 1"),
                {"version": future_version},
            )

        with pytest.raises(SchemaMigrationError, match="newer"):
            database.upgrade_schema()
        assert read_schema_version(database) == future_version
    finally:
        database.dispose()


def test_failed_migration_rolls_back_schema_and_version(tmp_path) -> None:
    database = make_database(tmp_path)

    def migration_one(connection) -> None:
        connection.exec_driver_sql("CREATE TABLE migration_one (id INTEGER)")

    def migration_two(connection) -> None:
        connection.exec_driver_sql("CREATE TABLE migration_two (id INTEGER)")
        raise RuntimeError("simulated migration failure")

    try:
        with pytest.raises(RuntimeError, match="simulated"):
            upgrade_schema(
                database.engine,
                migrations={1: migration_one, 2: migration_two},
                target_version=2,
            )

        table_names = set(inspect(database.engine).get_table_names())
        assert "schema_version" not in table_names
        assert "migration_one" not in table_names
        assert "migration_two" not in table_names
    finally:
        database.dispose()
