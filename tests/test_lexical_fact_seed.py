"""Idempotent lexical-fact import tests."""

from __future__ import annotations

import json

from app.ai.lexical_fact_validation import lexical_fact_content_hash
from app.ai.lexical_relation_candidate_validation import (
    lexical_relation_candidate_content_hash,
)
from app.ai.schemas import (
    LexicalEvidence,
    LexicalFactRecord,
    LexicalRelationCandidateGroup,
    LexicalRelationCandidateItem,
    LexicalRelationCandidateRecord,
    LexicalSectionStatus,
    LexicalSurfaceForm,
    VerbParadigm,
)
from app.db.lexical_fact_seed import (
    seed_lexical_facts,
    seed_lexical_relation_candidates,
)
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


def test_seed_relation_candidates_isolated_and_hash_idempotent(
    database, word_id
) -> None:
    record = LexicalRelationCandidateRecord(
        schema_version=1,
        word="adapt",
        level="CET4",
        source_kind="curated",
        source_meaning="适应；改编",
        groups=[
            LexicalRelationCandidateGroup(
                relation_type="synonym",
                synset_id="syn-adapt",
                ili="i-adapt",
                part_of_speech="verb",
                sense="适应",
                items=[
                    LexicalRelationCandidateItem(
                        word="adjust",
                        meaning="调整；适应",
                        english_definition="change to fit",
                        frequency=100,
                        evidence=[
                            LexicalEvidence(
                                source_id="oewn-2025",
                                source_version="2025",
                                field="synset.members",
                                locator="synset=syn-adapt",
                                source_sha256="b" * 64,
                            ),
                            LexicalEvidence(
                                source_id="omw-cmn-2",
                                source_version="2.0",
                                field="synset.labels",
                                locator="ili=i-adapt",
                                source_sha256="c" * 64,
                            ),
                        ],
                    )
                ],
            )
        ],
        selection_status="selected_single_sense",
        candidate_status="candidate_only",
        source_manifest_sha256="a" * 64,
        source="wordnet-cow-relation-candidates-v2",
        content_hash="0" * 64,
    )
    record = record.model_copy(
        update={"content_hash": lexical_relation_candidate_content_hash(record)}
    )
    with database.session() as session:
        assert seed_lexical_relation_candidates(session, [record]) == 1
    with database.session() as session:
        assert seed_lexical_relation_candidates(session, [record]) == 0
        fact = session.get(WordLexicalFact, word_id)
        assert fact is not None
        assert fact.candidate_status == "candidate_only"
        assert json.loads(fact.candidate_relations_json)[0]["items"][0]["word"] == (
            "adjust"
        )
        # Candidate import must never replace the formal projection.
        assert fact.forms_json == "[]"
