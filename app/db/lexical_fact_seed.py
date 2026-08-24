"""Validated, idempotent import of the lexical-fact artifact."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.lexical_fact_validation import (
    LexicalFactDataError,
    load_lexical_fact_records,
)
from app.ai.schemas import LexicalFactRecord
from app.db.models import Word, WordLexicalFact
from app.db.seed import VocabularySeedRow


def load_lexical_facts(
    jsonl_path: Path,
    *,
    sources: Sequence[VocabularySeedRow] | None = None,
    require_complete: bool = False,
) -> list[LexicalFactRecord]:
    """Load and validate before the caller opens its serialized write."""
    return load_lexical_fact_records(
        jsonl_path,
        sources=sources,
        require_complete=require_complete,
    )


def seed_lexical_facts(
    session: Session,
    records: Sequence[LexicalFactRecord],
) -> int:
    """Upsert facts by existing headword; never create a Word row."""
    word_ids = {
        word: word_id
        for word, word_id in session.execute(select(Word.word, Word.id)).all()
    }
    written = 0
    for record in records:
        # A fully validated ``missing`` record is useful for artifact
        # coverage, but has no learner-facing projection.  Omitting that
        # empty row keeps the runtime database small and makes startup cheap;
        # absence remains distinguishable from a validated empty paradigm via
        # the artifact/validator and the service's ``missing`` fallback.
        if not record.forms and not record.relations:
            continue
        word_id = word_ids.get(record.word)
        if word_id is None:
            continue
        fact = session.get(WordLexicalFact, word_id)
        if fact is not None and fact.content_hash == record.content_hash:
            continue
        if fact is None:
            fact = WordLexicalFact(word_id=word_id)
            session.add(fact)
        fact.forms_json = json.dumps(
            [paradigm.model_dump(mode="json") for paradigm in record.forms],
            ensure_ascii=False,
        )
        fact.relations_json = json.dumps(
            [group.model_dump(mode="json") for group in record.relations],
            ensure_ascii=False,
        )
        fact.forms_status = record.status.forms
        fact.relations_status = record.status.relations
        fact.source = record.source
        fact.content_hash = record.content_hash
        written += 1
    session.flush()
    return written


__all__ = [
    "LexicalFactDataError",
    "load_lexical_facts",
    "seed_lexical_facts",
]
