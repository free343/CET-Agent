"""Deterministic lexical-fact lookup must short-circuit model calls."""

from __future__ import annotations

from app.ai.schemas import (
    AIAnswer,
    DegreeParadigm,
    LexicalFactRecord,
    LexicalSectionStatus,
    LexicalSurfaceForm,
)
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
