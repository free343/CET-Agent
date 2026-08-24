"""Deterministic lexical-fact lookup must short-circuit model calls."""

from __future__ import annotations

from app.ai.schemas import (
    AIAnswer,
    DegreeParadigm,
    LexicalEvidence,
    LexicalFactRecord,
    LexicalRelationCandidateGroup,
    LexicalRelationCandidateItem,
    LexicalRelationGroup,
    LexicalRelationItem,
    LexicalSectionStatus,
    LexicalSurfaceForm,
)
from app.domain.lexical_display import format_part_of_speech
from app.domain.lexical_query import LexicalFactQuery
from app.services.ai_service import AIService


def _less() -> LexicalFactRecord:
    return LexicalFactRecord(
        schema_version=1,
        word="less",
        level="CET4",
        source_kind="open",
        source_meaning="较少的；较小的",
        forms=[
            DegreeParadigm(
                paradigm_type="degree",
                part_of_speech="adjective",
                gradability="contextual",
                forms=[
                    LexicalSurfaceForm(role="positive", value="little", sense="数量"),
                    LexicalSurfaceForm(role="comparative", value="less", sense="数量"),
                    LexicalSurfaceForm(role="superlative", value="least", sense="数量"),
                ],
            )
        ],
        relations=[],
        status=LexicalSectionStatus(
            forms="source_validated", relations="verified_empty"
        ),
        source="fixture",
        content_hash="0" * 64,
    )


def test_highest_question_returns_least_without_provider() -> None:
    query = LexicalFactQuery([_less()])
    answer = query.answer("less 的最高级是什么？", word="less")

    assert isinstance(answer, AIAnswer)
    assert "least" in answer.text
    assert answer.model == "deterministic-lexical-fact"
    assert answer.confidence == 1.0


def test_unrecognized_fact_reports_missing_instead_of_guessing() -> None:
    query = LexicalFactQuery([])
    answer = query.answer("这个词的过去式是什么？", word="unknown")

    assert answer is not None
    assert "没有经过验证" in answer.text
    assert answer.degraded is True


class _ExplodingProvider:
    model = "qwen2.5:3b"

    def generate(self, *_args, **_kwargs):  # pragma: no cover - must not execute
        raise AssertionError("verified lexical facts must not call a Provider")


def test_ai_service_short_circuits_verified_fact_before_provider(database) -> None:
    service = AIService(
        database,
        _ExplodingProvider(),
        lexical_fact_query=LexicalFactQuery([_less()]),
    )
    answer = service.ask("less 的最高级是什么？", context="word=less\nmeaning=较少")

    assert "least" in answer.text
    assert answer.model == "deterministic-lexical-fact"


def test_relation_part_of_speech_labels_are_compact() -> None:
    expected = {
        "adjective": "adj.",
        "adverb": "adv.",
        "noun": "n.",
        "verb": "v.",
    }
    assert {value: format_part_of_speech(value) for value in expected} == expected


def test_candidate_relation_answers_without_local_model(database) -> None:
    candidate = LexicalRelationCandidateGroup(
        relation_type="synonym",
        synset_id="syn-main",
        ili="i-main",
        part_of_speech="adjective",
        sense="主要的",
        items=[
            LexicalRelationCandidateItem(
                word="primary",
                meaning="主要+的",
                english_definition="important",
                frequency=100,
                evidence=[
                    LexicalEvidence(
                        source_id="oewn-2025",
                        source_version="2025",
                        field="synset.members",
                        locator="synset=syn-main",
                        source_sha256="a" * 64,
                    ),
                    LexicalEvidence(
                        source_id="omw-cmn-2",
                        source_version="2.0",
                        field="synset.labels",
                        locator="ili=i-main",
                        source_sha256="b" * 64,
                    ),
                ],
            ),
            LexicalRelationCandidateItem(
                word="principal",
                meaning="主要的",
                english_definition="important",
                frequency=90,
                evidence=[
                    LexicalEvidence(
                        source_id="oewn-2025",
                        source_version="2025",
                        field="synset.members",
                        locator="synset=syn-main",
                        source_sha256="a" * 64,
                    ),
                    LexicalEvidence(
                        source_id="omw-cmn-2",
                        source_version="2.0",
                        field="synset.labels",
                        locator="ili=i-main",
                        source_sha256="b" * 64,
                    ),
                ],
            ),
        ],
    )
    query = LexicalFactQuery(
        [],
        candidate_relations={"main": (candidate,)},
    )
    answer = query.answer("main 有什么近义词？", word="main")

    assert answer is not None
    assert "primary" in answer.text
    assert "近义：primary adj. 主要的" in answer.text
    assert "main" not in answer.text
    assert answer.text == ("近义：primary adj. 主要的\n近义：principal adj. 主要的")
    assert answer.model == "deterministic-lexical-candidate"
    assert answer.degraded is True
    assert query.answer("main 有什么近义词？") is not None

    formal = LexicalFactRecord(
        schema_version=1,
        word="main",
        level="CET4",
        source_kind="open",
        source_meaning="主要的",
        forms=[],
        relations=[
            LexicalRelationGroup(
                relation_type="synonym",
                part_of_speech="adjective",
                sense="主要的",
                items=[LexicalRelationItem(word="primary", meaning="主要的")],
            )
        ],
        status=LexicalSectionStatus(forms="missing", relations="source_validated"),
        source="fixture",
        content_hash="0" * 64,
    )
    combined = LexicalFactQuery([formal], candidate_relations={"main": (candidate,)})
    combined_answer = combined.answer("main 有什么近义词？", word="main")
    assert combined_answer is not None
    assert "近义：primary adj. 主要的" in combined_answer.text
    assert "primary" in combined_answer.text
    assert "近义：principal adj. 主要的" in combined_answer.text
    assert "main" not in combined_answer.text
    assert combined_answer.model == "deterministic-lexical-candidate"
    service = AIService(
        database,
        _ExplodingProvider(),
        lexical_fact_query=combined,
    )
    assert service.has_deterministic_lexical_answer("main 有什么近义词？") is True
