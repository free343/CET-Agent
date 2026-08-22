"""Application startup and idempotent database initialization."""

from __future__ import annotations

import logging

from app.config import PROJECT_ROOT, Settings, settings
from app.db.database import Database
from app.db.seed import ensure_learning_states, seed_words
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def initialize_database(app_settings: Settings = settings) -> Database:
    configure_logging(PROJECT_ROOT / "logs", app_settings.log_level)
    database = Database(app_settings.database_url)
    schema_version = database.upgrade_schema()
    with database.session() as session:
        inserted = sum(
            seed_words(session, source_path)
            for source_path in (
                PROJECT_ROOT / "data" / "sample_words.csv",
                PROJECT_ROOT / "data" / "cet_vocabulary_open.csv",
            )
        )
        missing_states = ensure_learning_states(session)
    logger.info(
        "Database initialized; schema_version=%s inserted_words=%s created_states=%s",
        schema_version,
        inserted,
        missing_states,
    )
    return database
