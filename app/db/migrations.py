"""Small, explicit, transactional database schema migrations."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from sqlalchemy import Connection, Engine, inspect, text

from app.db.models import Base

Migration = Callable[[Connection], None]

SCHEMA_VERSION_TABLE = "schema_version"


class SchemaMigrationError(RuntimeError):
    """Raised when the database schema cannot be upgraded safely."""


def _create_initial_schema(connection: Connection) -> None:
    """Adopt a fresh or pre-versioning MVP database as schema version 1."""
    Base.metadata.create_all(bind=connection)


def _add_fsrs_card_state(connection: Connection) -> None:
    columns = {
        column["name"]
        for column in inspect(connection).get_columns("learning_states")
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


MIGRATIONS: dict[int, Migration] = {
    1: _create_initial_schema,
    2: _add_fsrs_card_state,
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
            text(
                f"INSERT INTO {SCHEMA_VERSION_TABLE} (id, version) "
                "VALUES (1, 0)"
            )
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
        text(
            f"UPDATE {SCHEMA_VERSION_TABLE} SET version = :version WHERE id = 1"
        ),
        {"version": version},
    )
