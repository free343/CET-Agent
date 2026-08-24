"""Application startup and idempotent database initialization."""

from __future__ import annotations

import logging
import shutil

from app.ai.learning_aid_validation import SourceEntry
from app.config import ENV_FILE, PROJECT_ROOT, RUNTIME_ROOT, Settings, settings
from app.db.acquisition_seed import ensure_acquisition_states
from app.db.database import Database
from app.db.learning_aid_seed import load_learning_aid_records, seed_learning_aids
from app.db.lexical_fact_seed import load_lexical_facts, seed_lexical_facts
from app.db.models import WordLevel
from app.db.seed import (
    ensure_learning_states,
    load_vocabulary_rows,
    seed_vocabulary_rows,
)
from app.db.study_level_activation import activate_study_level
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def initialize_database(app_settings: Settings = settings) -> Database:
    configure_logging(RUNTIME_ROOT / "logs", app_settings.log_level)
    _install_runtime_config_template()
    database = Database(app_settings.database_url)
    try:
        schema_version = database.upgrade_schema()
        curated_csv = PROJECT_ROOT / "data" / "sample_words.csv"
        open_csv = PROJECT_ROOT / "data" / "cet_vocabulary_open.csv"
        aid_jsonl = PROJECT_ROOT / "data" / "word_learning_aids.jsonl"
        lexical_fact_jsonl = PROJECT_ROOT / "data" / "word_lexical_facts.jsonl"
        curated_rows = load_vocabulary_rows(curated_csv)
        open_rows = load_vocabulary_rows(open_csv)
        aid_sources = [
            SourceEntry(
                word=row.word,
                level=row.level.value,
                meaning=row.meaning,
                example=row.example,
                source_kind=source_kind,
            )
            for source_kind, rows in (
                ("curated", curated_rows),
                ("open", open_rows),
            )
            for row in rows
        ]
        aid_records = load_learning_aid_records(
            aid_jsonl,
            ordered_sources=aid_sources,
            require_complete=True,
            provenance_path=aid_jsonl.with_name("word_learning_aids.provenance.json"),
            source_files={curated_csv.name: curated_csv, open_csv.name: open_csv},
        )
        lexical_fact_records = load_lexical_facts(
            lexical_fact_jsonl,
            sources=[*curated_rows, *open_rows],
            require_complete=True,
        )
        with database.session() as session:
            database.begin_serialized_write(session)
            inserted = sum(
                seed_vocabulary_rows(session, rows)
                for rows in (curated_rows, open_rows)
            )
            missing_states = ensure_learning_states(session)
            missing_acquisition_states = ensure_acquisition_states(session)
            activation = activate_study_level(
                session,
                WordLevel(app_settings.study_level),
                open_rows,
            )
            aid_written = seed_learning_aids(session, aid_records)
            lexical_fact_written = seed_lexical_facts(session, lexical_fact_records)
        logger.info(
            "Database initialized; schema_version=%s inserted_words=%s "
            "created_states=%s level=%s newly_activated=%s rebased_words=%s "
            "acquisition_states=%s learning_aids=%s lexical_facts=%s",
            schema_version,
            inserted,
            missing_states,
            activation.level.value,
            activation.newly_activated,
            activation.rebased_word_count,
            missing_acquisition_states,
            aid_written,
            lexical_fact_written,
        )
        return database
    except Exception:
        database.dispose()
        raise


def _install_runtime_config_template() -> None:
    source = PROJECT_ROOT / ".env.example"
    target = ENV_FILE.with_name(".env.example")
    if source == target or target.exists() or not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
