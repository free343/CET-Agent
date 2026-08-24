"""Idempotent lexical-fact import tests."""

from __future__ import annotations

import json

from app.ai.lexical_fact_validation import lexical_fact_content_hash
from app.ai.schemas import (
    LexicalFactRecord,
    LexicalSectionStatus,
    LexicalSurfaceForm,
    VerbParadigm,
)
from app.db.lexical_fact_seed import seed_lexical_facts
from app.db.models import WordLexicalFact


def _record(word: str) -> LexicalFactRecord:
    record = LexicalFactRecord(
        schema_version=1,
        word=word,
        level="CET4",
        source_kind="curated",
        source_meaning="适应；改编",
        forms=[
            VerbParadigm(
                paradigm_type="verb",
                forms=[LexicalSurfaceForm(role="past", value="adapted")],
            )
        ],
        relations=[],
        status=LexicalSectionStatus(
            forms="source_validated", relations="verified_empty"
        ),
        source="fixture",
        content_hash="0" * 64,
    )
    return record.model_copy(update={"content_hash": lexical_fact_content_hash(record)})


def test_seed_lexical_facts_is_hash_idempotent(database, word_id) -> None:
    record = _record("adapt")
    with database.session() as session:
        assert seed_lexical_facts(session, [record]) == 1
    with database.session() as session:
        assert seed_lexical_facts(session, [record]) == 0
        fact = session.get(WordLexicalFact, word_id)
        assert fact is not None
        assert json.loads(fact.forms_json)[0]["forms"][0]["value"] == "adapted"
