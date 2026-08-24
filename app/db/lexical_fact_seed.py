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
from app.ai.lexical_relation_candidate_validation import (
    LexicalRelationCandidateDataError,
    load_runtime_lexical_relation_candidates,
)
from app.ai.schemas import LexicalFactRecord, LexicalRelationCandidateRecord
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
            fact = WordLexicalFact(
                word_id=word_id,
                forms_json="[]",
                relations_json="[]",
                forms_status="missing",
                relations_status="missing",
                source="",
                content_hash="0" * 64,
            )
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


def load_lexical_relation_candidates(
    jsonl_path: Path,
    provenance_path: Path,
    *,
    expected_words: set[str],
    manifest_path: Path | None = None,
) -> list[LexicalRelationCandidateRecord]:
    """Load the complete packaged candidate overlay before any database write."""
    return load_runtime_lexical_relation_candidates(
        jsonl_path,
        provenance_path,
        expected_words=expected_words,
        manifest_path=manifest_path,
    )


def seed_lexical_relation_candidates(
    session: Session,
    records: Sequence[LexicalRelationCandidateRecord],
) -> int:
    """Persist candidate relations without changing formal lexical facts."""
    word_ids = {
        word: word_id
        for word, word_id in session.execute(select(Word.word, Word.id)).all()
    }
    written = 0
    for record in records:
        word_id = word_ids.get(record.word)
        if word_id is None:
            continue
        fact = session.get(WordLexicalFact, word_id)
        if not record.groups:
            if fact is None or fact.candidate_status == "missing":
                continue
            fact.candidate_relations_json = "[]"
            fact.candidate_status = "missing"
            fact.candidate_source = ""
            fact.candidate_content_hash = ""
            written += 1
            continue
        if fact is None:
            fact = WordLexicalFact(
                word_id=word_id,
                forms_json="[]",
                relations_json="[]",
                forms_status="missing",
                relations_status="missing",
                source="",
                content_hash="0" * 64,
            )
            session.add(fact)
        elif (
            not fact.content_hash
            and fact.forms_json == "[]"
            and fact.relations_json == "[]"
        ):
            # Candidate-only rows do not own a formal artifact hash, but the
            # query projection still needs a schema-valid placeholder record.
            fact.content_hash = "0" * 64
        if (
            fact.candidate_status == "candidate_only"
            and fact.candidate_source == record.source
            and fact.candidate_content_hash == record.content_hash
        ):
            continue
        fact.candidate_relations_json = json.dumps(
            [group.model_dump(mode="json") for group in record.groups],
            ensure_ascii=False,
        )
        fact.candidate_status = "candidate_only"
        fact.candidate_source = record.source
        fact.candidate_content_hash = record.content_hash
        written += 1
    session.flush()
    return written


__all__ = [
    "LexicalFactDataError",
    "LexicalRelationCandidateDataError",
    "load_lexical_facts",
    "load_lexical_relation_candidates",
    "seed_lexical_facts",
    "seed_lexical_relation_candidates",
]
