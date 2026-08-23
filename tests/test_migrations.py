from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, inspect, select, text

from app.db.database import Database
from app.db.migrations import (
    CURRENT_SCHEMA_VERSION,
    SchemaMigrationError,
    upgrade_schema,
)
from app.db.models import Base, LearningState, ReviewLog, Word, WordLevel
from app.domain.fsrs_scheduler import Rating
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC


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


def test_version_four_repairs_demo_counts_without_removing_demo_history(
    tmp_path,
) -> None:
    database = make_database(tmp_path)
    reviewed_at = datetime(2026, 8, 22, 4, 0, tzinfo=UTC)
    try:
        Base.metadata.create_all(database.engine)
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
                "INSERT INTO schema_version (id, version) VALUES (1, 4)"
            )
        with database.session() as session:
            demo_only = Word(
                word="adept",
                meaning="熟练的",
                level=WordLevel.CET4,
                learning_state=LearningState(
                    next_review_at=reviewed_at,
                    review_count=4,
                    error_count=4,
                    lapse_count=4,
                    fsrs_state=2,
                    fsrs_step=None,
                ),
            )
            real_and_demo = Word(
                word="adapt",
                meaning="适应",
                level=WordLevel.CET4,
                learning_state=LearningState(
                    next_review_at=reviewed_at + timedelta(days=2),
                    last_review_at=reviewed_at,
                    review_count=5,
                    correct_count=1,
                    error_count=4,
                    lapse_count=4,
                    fsrs_state=2,
                    fsrs_step=None,
                ),
            )
            session.add_all((demo_only, real_and_demo))
            session.flush()
            session.execute(
                text(
                    "UPDATE learning_states SET fsrs_step = NULL "
                    "WHERE word_id IN (:demo_id, :mixed_id)"
                ),
                {"demo_id": demo_only.id, "mixed_id": real_and_demo.id},
            )
            for word in (demo_only, real_and_demo):
                for index in range(4):
                    session.add(
                        ReviewLog(
                            word_id=word.id,
                            reviewed_at=reviewed_at - timedelta(days=index),
                            rating=1,
                            is_correct=False,
                            response_time_ms=1_000,
                            question_type="demo_confusion",
                            previous_stability=1.0,
                            new_stability=0.5,
                            previous_difficulty=5.0,
                            new_difficulty=6.0,
                            scheduled_days=0.1,
                        )
                    )
            session.add(
                ReviewLog(
                    word_id=real_and_demo.id,
                    reviewed_at=reviewed_at,
                    rating=3,
                    is_correct=True,
                    response_time_ms=800,
                    question_type="meaning_recall",
                    previous_stability=0.4,
                    new_stability=2.0,
                    previous_difficulty=5.0,
                    new_difficulty=5.0,
                    scheduled_days=2.0,
                )
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        with database.session() as session:
            demo_state = session.scalar(
                select(LearningState).join(Word).where(Word.word == "adept")
            )
            mixed_state = session.scalar(
                select(LearningState).join(Word).where(Word.word == "adapt")
            )
            assert demo_state is not None
            assert mixed_state is not None
            assert (
                demo_state.review_count,
                demo_state.error_count,
                demo_state.lapse_count,
                demo_state.fsrs_state,
                demo_state.fsrs_step,
            ) == (0, 0, 0, 1, 0)
            assert demo_state.last_review_at is None
            assert (
                mixed_state.review_count,
                mixed_state.correct_count,
                mixed_state.error_count,
                mixed_state.lapse_count,
                mixed_state.fsrs_state,
                mixed_state.fsrs_step,
            ) == (1, 1, 0, 0, 2, None)
            assert mixed_state.last_review_at == reviewed_at
            assert session.scalar(select(func.count(ReviewLog.id))) == 9
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION

        submission = ReviewService(database).submit_review(
            demo_only.id,
            Rating.GOOD,
            900,
            question_type="meaning_choice_correct",
            user_answer="熟练的",
            reviewed_at=reviewed_at + timedelta(hours=1),
        )
        assert submission.word_id == demo_only.id
        assert submission.is_correct is True
        with database.session() as session:
            repaired_and_reviewed = session.scalar(
                select(LearningState).where(LearningState.word_id == demo_only.id)
            )
            assert repaired_and_reviewed is not None
            assert repaired_and_reviewed.review_count == 1
            assert repaired_and_reviewed.last_review_at == reviewed_at + timedelta(
                hours=1
            )
    finally:
        database.dispose()


def test_version_five_adds_review_undo_snapshot_columns(tmp_path) -> None:
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
                "INSERT INTO schema_version (id, version) VALUES (1, 5)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE review_logs (
                    id INTEGER PRIMARY KEY
                )
                """
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        columns = {
            column["name"]
            for column in inspect(database.engine).get_columns("review_logs")
        }
        assert {
            "previous_last_review_at",
            "previous_next_review_at",
            "previous_fsrs_state",
            "previous_fsrs_step",
        }.issubset(columns)
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_version_six_adds_favorite_wordbook_table(tmp_path) -> None:
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
                "INSERT INTO schema_version (id, version) VALUES (1, 6)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE words (
                    id INTEGER PRIMARY KEY
                )
                """
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        assert "favorite_words" in inspect(database.engine).get_table_names()
        columns = {
            column["name"]
            for column in inspect(database.engine).get_columns("favorite_words")
        }
        assert columns == {"word_id", "created_at"}
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_version_seven_adds_word_learning_aids_table(tmp_path) -> None:
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
                "INSERT INTO schema_version (id, version) VALUES (1, 7)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE words (
                    id INTEGER PRIMARY KEY
                )
                """
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        assert "word_learning_aids" in inspect(database.engine).get_table_names()
        columns = {
            column["name"]
            for column in inspect(database.engine).get_columns("word_learning_aids")
        }
        assert {
            "word_id",
            "example",
            "example_translation",
            "collocations_json",
            "word_family_json",
            "generator",
            "model",
            "prompt_version",
            "content_status",
            "content_hash",
            "created_at",
            "updated_at",
        }.issubset(columns)
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_version_eight_adds_learning_aid_feedback_table(tmp_path) -> None:
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
                "INSERT INTO schema_version (id, version) VALUES (1, 8)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE words (
                    id INTEGER PRIMARY KEY
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE word_learning_aids (
                    word_id INTEGER PRIMARY KEY
                )
                """
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        assert (
            "word_learning_aid_feedback" in inspect(database.engine).get_table_names()
        )
        columns = {
            column["name"]
            for column in inspect(database.engine).get_columns(
                "word_learning_aid_feedback"
            )
        }
        assert columns == {"word_id", "issue_type", "created_at", "updated_at"}
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_version_nine_adds_practice_logs_table(tmp_path) -> None:
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
                "INSERT INTO schema_version (id, version) VALUES (1, 9)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE words (
                    id INTEGER PRIMARY KEY
                )
                """
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION

        assert "practice_logs" in inspect(database.engine).get_table_names()
        columns = {
            column["name"]
            for column in inspect(database.engine).get_columns("practice_logs")
        }
        assert columns == {
            "id",
            "word_id",
            "practiced_at",
            "is_correct",
            "response_time_ms",
            "practice_scope",
            "question_type",
            "user_answer",
            "created_at",
        }
        assert read_schema_version(database) == CURRENT_SCHEMA_VERSION
    finally:
        database.dispose()


def test_version_ten_adds_acquisition_and_mastery_tables(tmp_path) -> None:
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
                "INSERT INTO schema_version (id, version) VALUES (1, 10)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE words (
                    id INTEGER PRIMARY KEY
                )
                """
            )

        assert database.upgrade_schema() == CURRENT_SCHEMA_VERSION
        inspector = inspect(database.engine)
        assert {
            "word_acquisition_states",
            "acquisition_attempts",
            "mastered_words",
        }.issubset(inspector.get_table_names())
        assert {
            "word_id",
            "proficiency_level",
            "completed_at",
            "created_at",
            "updated_at",
        } == {
            column["name"]
            for column in inspector.get_columns("word_acquisition_states")
        }
        assert {
            "id",
            "word_id",
            "attempted_at",
            "level_before",
            "level_after",
            "task_type",
            "is_correct",
            "self_confirmed",
            "response_time_ms",
            "user_answer",
            "created_at",
        } == {
            column["name"] for column in inspector.get_columns("acquisition_attempts")
        }
        assert {"word_id", "created_at"} == {
            column["name"] for column in inspector.get_columns("mastered_words")
        }
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
