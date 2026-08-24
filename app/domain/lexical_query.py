"""Deterministic answers for factual lexical questions.

The query layer intentionally has no Provider dependency.  A missing verified
fact is reported as missing instead of being delegated to the small local
model, whose free recall is not a correctness boundary for morphology.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.ai.schemas import AIAnswer, LexicalFactRecord, LexicalRelationGroup

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


class LexicalFactQuery:
    """Index validated records by headword and every known surface form."""

    def __init__(self, records: Iterable[LexicalFactRecord]) -> None:
        self._records: dict[str, LexicalFactRecord] = {}
        self._surface_to_headword: dict[str, str] = {}
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
        return bool(self._records)

    def answer(self, question: str, *, word: str | None = None) -> AIAnswer | None:
        normalized = question.strip().casefold()
        if not self._is_fact_question(normalized):
            return None
        headword = self._resolve_headword(word, normalized)
        record = self._records.get(headword or "")
        if record is None:
            return self._missing(word or "当前词", "词形或词汇关系")

        role = self._requested_role(normalized)
        if role is not None:
            return self._form_answer(record, role, word or record.word)
        if "序数" in normalized or "ordinal" in normalized:
            return self._form_answer(record, "ordinal", word or record.word)
        if any(marker in normalized for marker in ("近义", "同义", "synonym")):
            return self._relation_answer(record, "synonym")
        if "反义" in normalized or "antonym" in normalized:
            return self._relation_answer(record, "antonym")
        return self._missing(record.word, "对应的词形或关系")

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
        record: LexicalFactRecord,
        relation_type: str,
    ) -> AIAnswer:
        groups: list[LexicalRelationGroup] = [
            group for group in record.relations if group.relation_type == relation_type
        ]
        if not groups:
            return self._missing(record.word, f"{relation_type} 词")
        lines: list[str] = []
        for group in groups:
            items = "、".join(item.word for item in group.items)
            label = group.part_of_speech
            sense = f"（{group.sense}）" if group.sense else ""
            lines.append(f"{label}{sense}：{items}")
        return AIAnswer(
            text=f"{record.word} 的已验证{('近义词' if relation_type == 'synonym' else '反义词')}："
            + "；".join(lines),
            confidence=1.0,
            model="deterministic-lexical-fact",
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
