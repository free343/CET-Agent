"""Small, explicit, transactional database schema migrations."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from sqlalchemy import Connection, Engine, inspect, text

from app.db.models import (
    AcquisitionAttempt,
    Base,
    FavoriteWord,
    MasteredWord,
    PracticeLog,
    ReminderReviewLease,
    StudyLevelActivation,
    WordAcquisitionState,
    WordLearningAid,
    WordLearningAidFeedback,
)

Migration = Callable[[Connection], None]

SCHEMA_VERSION_TABLE = "schema_version"


class SchemaMigrationError(RuntimeError):
    """Raised when the database schema cannot be upgraded safely."""


def _create_initial_schema(connection: Connection) -> None:
    """Adopt a fresh or pre-versioning MVP database as schema version 1."""
    Base.metadata.create_all(bind=connection)


def _add_fsrs_card_state(connection: Connection) -> None:
    columns = {
        column["name"] for column in inspect(connection).get_columns("learning_states")
    }
    if "fsrs_state" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE learning_states "
            "ADD COLUMN fsrs_state INTEGER NOT NULL DEFAULT 1 "
            "CHECK (fsrs_state BETWEEN 1 AND 3)"
        )
    if "fsrs_step" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE learning_states "
            "ADD COLUMN fsrs_step INTEGER DEFAULT 0 "
            "CHECK (fsrs_step IS NULL OR fsrs_step >= 0)"
        )
    # Pre-FSRS rows have deterministic review history but no learning phase.
    # Reviewed cards are safely adopted as Review; untouched cards begin at
    # the single configured learning step.
    connection.execute(
        text(
            """
            UPDATE learning_states
            SET fsrs_state = CASE WHEN review_count > 0 THEN 2 ELSE 1 END,
                fsrs_step = CASE WHEN review_count > 0 THEN NULL ELSE 0 END
            """
        )
    )


def _add_study_level_activation(connection: Connection) -> None:
    StudyLevelActivation.__table__.create(bind=connection, checkfirst=True)


def _add_reminder_review_leases(connection: Connection) -> None:
    ReminderReviewLease.__table__.create(bind=connection, checkfirst=True)


def _repair_demo_learning_states(connection: Connection) -> None:
    """Remove synthetic graph-demo increments from persisted FSRS state.

    ``demo_confusion`` rows intentionally remain in ``review_logs`` so the
    repeatable analysis demo still has evidence. They are not user reviews and
    therefore must not contribute to the card state used by FSRS.
    """
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if not {"learning_states", "review_logs"}.issubset(tables):
        return
    learning_columns = {
        column["name"] for column in inspector.get_columns("learning_states")
    }
    review_columns = {column["name"] for column in inspector.get_columns("review_logs")}
    required_learning_columns = {
        "word_id",
        "review_count",
        "error_count",
        "lapse_count",
        "last_review_at",
        "fsrs_state",
        "fsrs_step",
    }
    if not required_learning_columns.issubset(learning_columns) or not {
        "word_id",
        "question_type",
    }.issubset(review_columns):
        return

    demo_count = (
        "(SELECT COUNT(*) FROM review_logs AS demo_logs "
        "WHERE demo_logs.word_id = learning_states.word_id "
        "AND demo_logs.question_type = 'demo_confusion')"
    )
    connection.execute(
        text(
            f"""
            UPDATE learning_states
            SET review_count = CASE
                    WHEN review_count > {demo_count}
                    THEN review_count - {demo_count}
                    ELSE 0
                END,
                error_count = CASE
                    WHEN error_count > {demo_count}
                    THEN error_count - {demo_count}
                    ELSE 0
                END,
                lapse_count = CASE
                    WHEN lapse_count > {demo_count}
                    THEN lapse_count - {demo_count}
                    ELSE 0
                END
            WHERE {demo_count} > 0
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE learning_states
            SET fsrs_state = 1,
                fsrs_step = 0
            WHERE review_count = 0
              AND last_review_at IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM review_logs AS demo_logs
                  WHERE demo_logs.word_id = learning_states.word_id
                    AND demo_logs.question_type = 'demo_confusion'
              )
            """
        )
    )


def _add_review_undo_snapshots(connection: Connection) -> None:
    """Add nullable pre-review state used by safe one-step undo.

    Existing history intentionally remains non-undoable because reconstructing
    its exact FSRS state from partial legacy data would be unsafe.
    """
    if "review_logs" not in inspect(connection).get_table_names():
        return
    columns = {
        column["name"] for column in inspect(connection).get_columns("review_logs")
    }
    additions = {
        "previous_last_review_at": "DATETIME",
        "previous_next_review_at": "DATETIME",
        "previous_fsrs_state": "INTEGER",
        "previous_fsrs_step": "INTEGER",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE review_logs ADD COLUMN {name} {sql_type}"
            )


def _add_favorite_wordbook(connection: Connection) -> None:
    FavoriteWord.__table__.create(bind=connection, checkfirst=True)


def _add_word_learning_aids(connection: Connection) -> None:
    WordLearningAid.__table__.create(bind=connection, checkfirst=True)


def _add_word_learning_aid_feedback(connection: Connection) -> None:
    WordLearningAidFeedback.__table__.create(bind=connection, checkfirst=True)


def _add_practice_logs(connection: Connection) -> None:
    PracticeLog.__table__.create(bind=connection, checkfirst=True)


def _add_acquisition_and_mastery_state(connection: Connection) -> None:
    WordAcquisitionState.__table__.create(bind=connection, checkfirst=True)
    AcquisitionAttempt.__table__.create(bind=connection, checkfirst=True)
    MasteredWord.__table__.create(bind=connection, checkfirst=True)


MIGRATIONS: dict[int, Migration] = {
    1: _create_initial_schema,
    2: _add_fsrs_card_state,
    3: _add_study_level_activation,
    4: _add_reminder_review_leases,
    5: _repair_demo_learning_states,
    6: _add_review_undo_snapshots,
    7: _add_favorite_wordbook,
    8: _add_word_learning_aids,
    9: _add_word_learning_aid_feedback,
    10: _add_practice_logs,
    11: _add_acquisition_and_mastery_state,
}
CURRENT_SCHEMA_VERSION = max(MIGRATIONS)


def upgrade_schema(
    engine: Engine,
    *,
    migrations: Mapping[int, Migration] | None = None,
    target_version: int | None = None,
) -> int:
    """Upgrade a database in one transaction and return its schema version.

    The injectable registry and target are intentionally narrow test seams. A
    production caller should use the defaults so every version between the
    stored version and ``CURRENT_SCHEMA_VERSION`` is applied in order.
    """
    use_current_schema_for_fresh_database = (
        migrations is None and target_version is None
    )
    registry = dict(MIGRATIONS if migrations is None else migrations)
    target = CURRENT_SCHEMA_VERSION if target_version is None else target_version
    if target < 0:
        raise ValueError("Schema target version cannot be negative")

    with engine.connect() as connection:
        try:
            _begin_migration_transaction(connection)
            _ensure_version_table(connection)
            current = _read_version(connection)
            if (
                current == 0
                and use_current_schema_for_fresh_database
                and _is_fresh_database(connection)
            ):
                # Fresh installs use the current metadata snapshot directly.
                # Historical migrations remain frozen upgrade steps for older
                # files and do not need to recreate every past schema first.
                Base.metadata.create_all(bind=connection)
                _write_version(connection, target)
                connection.commit()
                return target
            if current > target:
                raise SchemaMigrationError(
                    "Database schema version "
                    f"{current} is newer than this application supports ({target})."
                )

            for version in range(current + 1, target + 1):
                migration = registry.get(version)
                if migration is None:
                    raise SchemaMigrationError(
                        f"No database migration is registered for version {version}."
                    )
                migration(connection)
                _write_version(connection, version)

            connection.commit()
            return target
        except Exception:
            connection.rollback()
            raise


def _begin_migration_transaction(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        # Reserve the single SQLite writer before reading the stored version so
        # two application processes cannot both apply the same migration.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.begin()


def _is_fresh_database(connection: Connection) -> bool:
    table_names = set(inspect(connection).get_table_names())
    return table_names <= {SCHEMA_VERSION_TABLE}


def _ensure_version_table(connection: Connection) -> None:
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
                id INTEGER NOT NULL PRIMARY KEY,
                version INTEGER NOT NULL,
                CONSTRAINT ck_schema_version_singleton CHECK (id = 1),
                CONSTRAINT ck_schema_version_nonnegative CHECK (version >= 0)
            )
            """
        )
    )
    rows = connection.execute(
        text(f"SELECT id, version FROM {SCHEMA_VERSION_TABLE}")
    ).all()
    if not rows:
        connection.execute(
            text(f"INSERT INTO {SCHEMA_VERSION_TABLE} (id, version) VALUES (1, 0)")
        )
        return
    if len(rows) != 1 or rows[0].id != 1:
        raise SchemaMigrationError("Database schema version metadata is invalid.")


def _read_version(connection: Connection) -> int:
    version = connection.execute(
        text(f"SELECT version FROM {SCHEMA_VERSION_TABLE} WHERE id = 1")
    ).scalar_one()
    if not isinstance(version, int) or version < 0:
        raise SchemaMigrationError("Database schema version metadata is invalid.")
    return version


def _write_version(connection: Connection, version: int) -> None:
    connection.execute(
        text(f"UPDATE {SCHEMA_VERSION_TABLE} SET version = :version WHERE id = 1"),
        {"version": version},
    )
