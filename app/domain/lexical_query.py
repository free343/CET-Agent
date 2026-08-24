"""Deterministic answers for factual lexical questions.

The query layer intentionally has no Provider dependency.  A missing verified
fact is reported as missing instead of being delegated to the small local
model, whose free recall is not a correctness boundary for morphology.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.ai.schemas import (
    AIAnswer,
    LexicalFactRecord,
    LexicalRelationCandidateGroup,
    LexicalRelationGroup,
)
from app.domain.lexical_display import format_part_of_speech

_FACT_MARKERS = (
    "最高级",
    "比较级",
    "过去式",
    "过去分词",
    "现在分词",
    "第三人称",
    "复数",
    "序数",
    "词形",
    "superlative",
    "comparative",
    "past tense",
    "past participle",
    "present participle",
    "third person",
    "plural",
    "ordinal",
    "synonym",
    "antonym",
    "近义词",
    "同义词",
    "反义词",
)


def _clean_relation_text(value: str) -> str:
    """Remove source token markers before rendering a learner-facing relation."""
    return " ".join(value.replace("+", "").split())


class LexicalFactQuery:
    """Index validated records by headword and every known surface form."""

    def __init__(
        self,
        records: Iterable[LexicalFactRecord],
        *,
        candidate_relations: dict[str, tuple[LexicalRelationCandidateGroup, ...]]
        | None = None,
    ) -> None:
        self._records: dict[str, LexicalFactRecord] = {}
        self._surface_to_headword: dict[str, str] = {}
        self._candidate_relations = {
            word.casefold().strip(): groups
            for word, groups in (candidate_relations or {}).items()
            if word.strip() and groups
        }
        for word in self._candidate_relations:
            self._surface_to_headword.setdefault(word, word)
        for record in records:
            key = record.word.casefold().strip()
            if not key:
                continue
            self._records[key] = record
            self._surface_to_headword[key] = key
            for paradigm in record.forms:
                for form in paradigm.forms:
                    for surface in form.value.casefold().strip().split("/"):
                        if surface:
                            self._surface_to_headword.setdefault(surface, key)

    @property
    def has_records(self) -> bool:
        return bool(self._records or self._candidate_relations)

    def can_answer(self, question: str, *, word: str | None = None) -> bool:
        """Return whether a requested lexical fact has a non-empty local value."""
        normalized = question.strip().casefold()
        if not self._is_fact_question(normalized):
            return False
        headword = self._resolve_headword(word, normalized)
        record = self._records.get(headword or "")
        candidate_groups = self._candidate_relations.get(headword or "", ())
        if record is None and not candidate_groups:
            return False
        role = self._requested_role(normalized)
        if role is not None:
            return record is not None and any(
                form.role == role
                for paradigm in record.forms
                for form in paradigm.forms
            )
        if "序数" in normalized or "ordinal" in normalized:
            return record is not None and any(
                form.role == "ordinal"
                for paradigm in record.forms
                for form in paradigm.forms
            )
        if any(marker in normalized for marker in ("近义", "同义", "synonym")):
            return bool(
                record is not None
                and any(group.relation_type == "synonym" for group in record.relations)
            ) or any(group.relation_type == "synonym" for group in candidate_groups)
        if "反义" in normalized or "antonym" in normalized:
            return bool(
                record is not None
                and any(group.relation_type == "antonym" for group in record.relations)
            ) or any(group.relation_type == "antonym" for group in candidate_groups)
        return False

    def answer(self, question: str, *, word: str | None = None) -> AIAnswer | None:
        normalized = question.strip().casefold()
        if not self._is_fact_question(normalized):
            return None
        headword = self._resolve_headword(word, normalized)
        record = self._records.get(headword or "")
        if record is None and not self._candidate_relations.get(headword or ""):
            return self._missing(word or "当前词", "词形或词汇关系")

        role = self._requested_role(normalized)
        if role is not None:
            if record is None:
                return self._missing(word or "当前词", f"{role} 词形")
            return self._form_answer(record, role, word or record.word)
        if "序数" in normalized or "ordinal" in normalized:
            if record is None:
                return self._missing(word or "当前词", "ordinal 词形")
            return self._form_answer(record, "ordinal", word or record.word)
        if any(marker in normalized for marker in ("近义", "同义", "synonym")):
            return self._relation_answer(
                record,
                "synonym",
                self._candidate_relations.get(headword or "", ()),
            )
        if "反义" in normalized or "antonym" in normalized:
            return self._relation_answer(
                record,
                "antonym",
                self._candidate_relations.get(headword or "", ()),
            )
        return self._missing(
            word or (record.word if record is not None else "当前词"),
            "对应的词形或关系",
        )

    @staticmethod
    def _is_fact_question(question: str) -> bool:
        return any(marker in question for marker in _FACT_MARKERS)

    def _resolve_headword(self, word: str | None, question: str) -> str | None:
        if word:
            normalized = word.casefold().strip()
            return self._surface_to_headword.get(normalized, normalized)
        # This fallback is intentionally conservative: only an exact indexed
        # token in the question is accepted, never a guessed headword.
        for token in re.findall(r"[a-z]+(?:[-'][a-z]+)?", question):
            if token in self._surface_to_headword:
                return self._surface_to_headword[token]
        return None

    @staticmethod
    def _requested_role(question: str) -> str | None:
        if "最高级" in question or "superlative" in question:
            return "superlative"
        if "比较级" in question or "comparative" in question:
            return "comparative"
        if "过去分词" in question or "past participle" in question:
            return "past_participle"
        if "过去式" in question or "past tense" in question:
            return "past"
        if "现在分词" in question or "present participle" in question:
            return "present_participle"
        if "第三人称" in question or "third person" in question:
            return "third_person_singular"
        if "复数" in question or "plural" in question:
            return "plural"
        if "序数" in question or "ordinal" in question:
            return "ordinal"
        return None

    def _form_answer(
        self,
        record: LexicalFactRecord,
        role: str,
        requested_word: str,
    ) -> AIAnswer:
        matches = [
            (paradigm, form)
            for paradigm in record.forms
            for form in paradigm.forms
            if form.role == role
        ]
        if not matches:
            return self._missing(requested_word, f"{role} 词形")
        values: list[str] = []
        for paradigm, form in matches:
            value = form.value
            detail = f"（{form.sense}）" if form.sense else ""
            if form.note:
                detail += f"；{form.note}"
            if value + detail not in values:
                values.append(value + detail)
        return AIAnswer(
            text=f"{requested_word} 的已验证 {self._role_label(role)}："
            + "；".join(values),
            confidence=1.0,
            model="deterministic-lexical-fact",
        )

    def _relation_answer(
        self,
        record: LexicalFactRecord | None,
        relation_type: str,
        candidate_groups: tuple[LexicalRelationCandidateGroup, ...] = (),
    ) -> AIAnswer:
        formal_groups: list[LexicalRelationGroup] = [
            group
            for group in (record.relations if record is not None else ())
            if group.relation_type == relation_type
        ]
        if formal_groups:
            formal_answer = self._format_relation_answer(
                relation_type,
                formal_groups,
                model="deterministic-lexical-fact",
            )
            candidate_answer = self._candidate_relation_answer(
                relation_type,
                candidate_groups,
                excluded={
                    item.word.casefold()
                    for group in formal_groups
                    for item in group.items
                },
            )
            if candidate_answer is None:
                return formal_answer
            return AIAnswer(
                text=f"{formal_answer.text}\n{candidate_answer}",
                confidence=1.0,
                model="deterministic-lexical-candidate",
                degraded=True,
            )
        groups = [
            group for group in candidate_groups if group.relation_type == relation_type
        ]
        if not groups:
            return self._missing(
                record.word if record is not None else "当前词", f"{relation_type} 词"
            )
        candidate_text = self._candidate_relation_answer(
            relation_type,
            tuple(groups),
            excluded=set(),
        )
        if candidate_text is None:
            return self._missing(
                record.word if record is not None else "当前词", f"{relation_type} 词"
            )
        return AIAnswer(
            text=candidate_text,
            confidence=1.0,
            model="deterministic-lexical-candidate",
            degraded=True,
        )

    @staticmethod
    def _candidate_relation_answer(
        relation_type: str,
        groups: tuple[LexicalRelationCandidateGroup, ...],
        *,
        excluded: set[str],
    ) -> str | None:
        lines: list[str] = []
        relation_label = "近义" if relation_type == "synonym" else "反义"
        for group in groups:
            for item in group.items:
                if item.word.casefold() in excluded:
                    continue
                details = " ".join(
                    value
                    for value in (
                        item.word,
                        format_part_of_speech(group.part_of_speech),
                        _clean_relation_text(item.meaning),
                    )
                    if value
                )
                if details:
                    lines.append(f"{relation_label}：{details}")
        if not lines:
            return None
        return "\n".join(lines)

    @staticmethod
    def _format_relation_answer(
        relation_type: str,
        groups: list[LexicalRelationGroup],
        *,
        model: str,
    ) -> AIAnswer:
        lines: list[str] = []
        relation_label = "近义" if relation_type == "synonym" else "反义"
        for group in groups:
            for item in group.items:
                details = " ".join(
                    value
                    for value in (
                        item.word,
                        format_part_of_speech(group.part_of_speech),
                        _clean_relation_text(item.meaning),
                    )
                    if value
                )
                if details:
                    lines.append(f"{relation_label}：{details}")
        return AIAnswer(
            text="\n".join(lines),
            confidence=1.0,
            model=model,
        )

    @staticmethod
    def _role_label(role: str) -> str:
        return {
            "superlative": "最高级",
            "comparative": "比较级",
            "past": "过去式",
            "past_participle": "过去分词",
            "present_participle": "现在分词",
            "third_person_singular": "第三人称单数",
            "plural": "复数",
            "ordinal": "序数形式",
        }.get(role, "词形")

    @staticmethod
    def _missing(word: str, fact: str) -> AIAnswer:
        return AIAnswer(
            text=f"当前词卡没有经过验证的{fact}（{word}）。为避免猜错，未调用本地模型。",
            confidence=1.0,
            model="deterministic-lexical-fact",
            degraded=True,
        )
