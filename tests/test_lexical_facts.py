"""Red/contract tests for the verified adaptive lexical-fact layer."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.ai.schemas import (
    DegreeParadigm,
    LexicalFactRecord,
    LexicalRelationGroup,
    LexicalRelationItem,
    LexicalSectionStatus,
    LexicalSurfaceForm,
    NounParadigm,
)
from app.db.seed import load_vocabulary_rows
from scripts.generate_lexical_facts import build_record


def _record(word: str, forms: list, relations: list | None = None) -> LexicalFactRecord:
    return LexicalFactRecord(
        schema_version=1,
        word=word,
        level="CET4",
        source_kind="open",
        source_meaning="测试释义",
        forms=forms,
        relations=relations or [],
        status=LexicalSectionStatus(
            forms="source_validated" if forms else "verified_empty",
            relations="source_validated" if relations else "verified_empty",
        ),
        source="audited-fixture-v1",
        content_hash="0" * 64,
    )


def test_typed_paradigm_keeps_less_and_few_as_different_chains() -> None:
    less = _record(
        "less",
        [
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
    )
    few = _record(
        "few",
        [
            DegreeParadigm(
                paradigm_type="degree",
                part_of_speech="adjective",
                gradability="contextual",
                forms=[
                    LexicalSurfaceForm(
                        role="positive", value="few", sense="可数名词数量"
                    ),
                    LexicalSurfaceForm(
                        role="comparative", value="fewer", sense="可数名词数量"
                    ),
                    LexicalSurfaceForm(
                        role="superlative", value="fewest", sense="可数名词数量"
                    ),
                ],
            )
        ],
    )

    assert less.forms[0].forms[-1].value == "least"
    assert few.forms[0].forms[-1].value == "fewest"


def test_relations_are_grouped_by_pos_and_sense() -> None:
    record = _record(
        "main",
        [],
        [
            LexicalRelationGroup(
                relation_type="synonym",
                part_of_speech="adjective",
                sense="主要的",
                items=[
                    LexicalRelationItem(
                        word="primary",
                        meaning="主要的",
                        note="可互换但 primary 更常用于正式分类",
                    )
                ],
            )
        ],
    )
    assert record.relations[0].items[0].word == "primary"
    assert record.relations[0].part_of_speech == "adjective"


def test_invalid_empty_relation_group_is_rejected() -> None:
    try:
        LexicalRelationGroup(
            relation_type="antonym",
            part_of_speech="adjective",
            items=[],
        )
    except ValidationError as exc:
        assert "items" in str(exc)
    else:  # pragma: no cover - the assertion is the failure signal
        raise AssertionError("empty lexical relation groups must be rejected")


def test_noun_countability_is_not_encoded_as_a_word_family() -> None:
    record = _record(
        "information",
        [
            NounParadigm(
                paradigm_type="noun",
                countability="uncountable",
                forms=[
                    LexicalSurfaceForm(
                        role="singular",
                        value="information",
                        note="通常不可数，不用 informations 表示信息",
                    )
                ],
            )
        ],
    )
    assert record.forms[0].paradigm_type == "noun"
    assert record.forms[0].countability == "uncountable"


def test_bundled_less_record_exposes_little_less_least_chain() -> None:
    rows = load_vocabulary_rows(Path("data/cet_vocabulary_open.csv"))
    record = build_record(next(row for row in rows if row.word == "less"))
    values = [form.value for paradigm in record.forms for form in paradigm.forms]
    assert values[:3] == ["little", "less", "least"]
