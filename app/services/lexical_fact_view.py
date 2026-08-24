"""Bounded learner-facing projection of verified lexical facts and aids."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from app.ai.schemas import LexicalParadigm, LexicalRelationCandidateGroup
from app.db.models import WordLearningAid, WordLexicalFact
from app.domain.lexical_display import format_part_of_speech
from app.services.learning_aid_view import format_collocations, format_word_family

_PARADIGM_ADAPTER = TypeAdapter(LexicalParadigm)
_CANDIDATE_GROUP_ADAPTER = TypeAdapter(LexicalRelationCandidateGroup)


@dataclass(frozen=True, slots=True)
class LexicalFactSection:
    key: str
    title: str
    items: tuple[str, ...]
    status: str
    verified: bool
    reportable: bool = True


@dataclass(frozen=True, slots=True)
class LexicalFactsView:
    sections: tuple[LexicalFactSection, ...]
    forms_status: str = "missing"
    relations_status: str = "missing"


_ROLE_LABELS = {
    "singular": "单数",
    "plural": "复数",
    "base": "原形",
    "third_person_singular": "第三人称单数",
    "past": "过去式",
    "past_participle": "过去分词",
    "present_participle": "现在分词",
    "positive": "原级",
    "comparative": "比较级",
    "superlative": "最高级",
    "cardinal": "基数词",
    "ordinal": "序数词",
    "subject": "主格",
    "object": "宾格",
    "possessive": "所有格",
    "reflexive": "反身形式",
}


def build_lexical_facts_view(
    fact: WordLexicalFact | None,
    aid: WordLearningAid | None,
    *,
    feedback_reported: bool = False,
) -> LexicalFactsView:
    """Return only non-empty sections, ordered by learner value."""
    sections: list[LexicalFactSection] = []
    forms_status = fact.forms_status if fact is not None else "missing"
    relations_status = fact.relations_status if fact is not None else "missing"
    if (
        fact is not None
        and fact.candidate_status == "candidate_only"
        and relations_status == "missing"
    ):
        relations_status = "candidate_only"
    form_items = _format_forms(fact)
    if form_items:
        sections.append(
            LexicalFactSection(
                key="forms",
                title="词形",
                items=form_items,
                status="已验证",
                verified=True,
            )
        )

    collocations = format_collocations(aid)
    if collocations:
        sections.append(
            LexicalFactSection(
                key="collocations",
                title="搭配",
                items=collocations,
                status="AI · 已反馈" if feedback_reported else "AI · 未审核",
                verified=False,
            )
        )

    relation_items = _format_relations(fact)
    candidate_relation_items = _format_relation_candidates(
        fact,
        excluded_words=_relation_words(fact),
    )
    relation_items = _unique_trimmed(
        [*relation_items, *candidate_relation_items],
        8,
    )
    if relation_items:
        has_formal_relations = bool(_format_relations(fact))
        has_candidate_relations = bool(candidate_relation_items)
        if has_candidate_relations and has_formal_relations:
            relation_status = "已验证 + 来源候选"
        elif has_candidate_relations:
            relation_status = "来源候选 · 待审核"
        else:
            relation_status = "已验证"
        sections.append(
            LexicalFactSection(
                key="relations",
                title="近反义",
                items=relation_items,
                status=relation_status,
                verified=not has_candidate_relations,
                reportable=False,
            )
        )

    family = format_word_family(aid)
    derivative_items = _format_derivatives(fact) + list(family)
    if derivative_items:
        sections.append(
            LexicalFactSection(
                key="derivatives",
                title="派生词",
                items=tuple(derivative_items[:6]),
                status="AI · 已反馈" if feedback_reported else "AI · 未审核",
                verified=False,
            )
        )
    return LexicalFactsView(tuple(sections), forms_status, relations_status)


def _format_forms(fact: WordLexicalFact | None) -> tuple[str, ...]:
    if fact is None:
        return ()
    try:
        raw = json.loads(fact.forms_json)
        if not isinstance(raw, list):
            return ()
        paradigms = [_PARADIGM_ADAPTER.validate_python(item) for item in raw]
    except (TypeError, ValueError, ValidationError):
        return ()
    items: list[str] = []
    for paradigm in paradigms:
        for form in paradigm.forms:
            label = _ROLE_LABELS.get(form.role, form.role)
            detail = f"｜{form.sense}" if form.sense else ""
            if form.note:
                detail += f"；{form.note}"
            if form.phonetic:
                detail += f" [{form.phonetic}]"
            labels = " / ".join(
                value for value in (form.region, form.register) if value
            )
            if labels:
                detail += f"（{labels}）"
            items.append(f"{label} {form.value}{detail}")
    return tuple(_unique_trimmed(items, 8))


def _format_relations(fact: WordLexicalFact | None) -> tuple[str, ...]:
    if fact is None:
        return ()
    try:
        raw = json.loads(fact.relations_json)
        if not isinstance(raw, list):
            return ()
    except (TypeError, ValueError):
        return ()
    items: list[str] = []
    relation_labels = {"synonym": "近义", "antonym": "反义", "derivative": "派生"}
    for group in raw:
        if not isinstance(group, dict):
            continue
        if group.get("relation_type") == "derivative":
            continue
        relation = relation_labels.get(str(group.get("relation_type")), "关系")
        pos = format_part_of_speech(str(group.get("part_of_speech") or ""))
        for item in group.get("items", []):
            if not isinstance(item, dict):
                continue
            word = str(item.get("word") or "").strip()
            meaning = str(item.get("meaning") or "").strip()
            if word and meaning:
                details = " ".join(value for value in (word, pos, meaning) if value)
                items.append(f"{relation}：{details}")
    return tuple(_unique_trimmed(items, 8))


def _format_relation_candidates(
    fact: WordLexicalFact | None,
    *,
    excluded_words: set[str],
) -> tuple[str, ...]:
    if fact is None or fact.candidate_status != "candidate_only":
        return ()
    try:
        raw = json.loads(fact.candidate_relations_json)
        if not isinstance(raw, list):
            return ()
        groups = [_CANDIDATE_GROUP_ADAPTER.validate_python(item) for item in raw]
    except (TypeError, ValueError, ValidationError):
        return ()
    items: list[str] = []
    relation_labels = {"synonym": "近义", "antonym": "反义"}
    for group in groups:
        relation = relation_labels.get(group.relation_type, "关系候选")
        for item in group.items:
            if item.word.casefold() in excluded_words:
                continue
            meaning = _clean_cow_label(item.meaning)
            if item.word and meaning:
                details = " ".join(
                    value
                    for value in (
                        item.word,
                        format_part_of_speech(group.part_of_speech),
                        meaning,
                    )
                    if value
                )
                items.append(f"{relation}：{details}")
    return tuple(_unique_trimmed(items, 8))


def _relation_words(fact: WordLexicalFact | None) -> set[str]:
    if fact is None:
        return set()
    try:
        raw = json.loads(fact.relations_json)
    except (TypeError, ValueError):
        return set()
    words: set[str] = set()
    for group in raw if isinstance(raw, list) else []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items", []):
            if isinstance(item, dict) and item.get("word"):
                words.add(str(item["word"]).casefold())
    return words


def _clean_cow_label(value: str) -> str:
    return " ".join(value.replace("+", "").split())


def _format_derivatives(fact: WordLexicalFact | None) -> list[str]:
    if fact is None:
        return []
    try:
        raw = json.loads(fact.relations_json)
    except (TypeError, ValueError):
        return []
    items: list[str] = []
    for group in raw if isinstance(raw, list) else []:
        if not isinstance(group, dict) or group.get("relation_type") != "derivative":
            continue
        for item in group.get("items", []):
            if isinstance(item, dict) and item.get("word") and item.get("meaning"):
                items.append(f"{item['word']}｜{item['meaning']}")
    return list(_unique_trimmed(items, 6))


def _unique_trimmed(items: list[str], limit: int) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = " ".join(str(item).split()).strip()[:240]
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
        if len(result) >= limit:
            break
    return tuple(result)
