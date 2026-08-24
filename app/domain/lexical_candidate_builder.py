"""Build candidate-only form comparisons from the pinned ECDICT exchange field.

This module is intentionally conservative.  It compares source evidence with
the current formal artifact, labels disagreements for human review, and never
promotes a candidate or writes to the database.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.ai.schemas import (
    LexicalEvidence,
    LexicalFactCandidateRecord,
    LexicalFactRecord,
    LexicalFormCandidate,
)
from app.db.seed import VocabularySeedRow
from app.domain.lexical_source_readers import ECDICTEntry

ROLE_TO_EXCHANGE: dict[str, str] = {
    "plural": "s",
    "past": "p",
    "past_participle": "d",
    "present_participle": "i",
    "third_person_singular": "3",
    "comparative": "r",
    "superlative": "t",
}
FORM_CANDIDATE_SOURCE = "ecdict-exchange-candidates-v1"
_CONSONANTS = set("bcdfghjklmnpqrstvwxyz")
_POS_PATTERN = re.compile(r"\b(adv|vt|vi|v|n|a)\.")


def build_candidate_record(
    row: VocabularySeedRow,
    fact: LexicalFactRecord,
    entry: ECDICTEntry | None,
    *,
    source_version: str,
    source_sha256: str,
    manifest_sha256: str,
) -> LexicalFactCandidateRecord:
    """Build one complete candidate record for ``row``.

    A role is emitted only when ECDICT supplies the documented exchange code.
    Empty candidate lists therefore mean that this source did not provide a
    comparable role, not that the current artifact is proven complete.
    """

    candidates: list[LexicalFormCandidate] = []
    if entry is not None:
        current_by_role = _fact_forms_by_role(fact)
        for role, code in ROLE_TO_EXCHANGE.items():
            source_forms = _flatten_forms(entry.exchange.get(code, ()))
            if not source_forms:
                continue
            current_forms = current_by_role.get(role, [])
            outcome, conflict_kind = _compare_forms(
                row.word,
                role,
                current_forms,
                source_forms,
                entry,
            )
            candidates.append(
                LexicalFormCandidate(
                    role=role,
                    current_forms=current_forms,
                    source_forms=source_forms,
                    outcome=outcome,
                    conflict_kind=conflict_kind,
                    evidence=[
                        LexicalEvidence(
                            source_id="ecdict",
                            source_version=source_version,
                            field="exchange",
                            locator=(f"ecdict.csv:word={row.word}:code={code}"),
                            source_sha256=source_sha256,
                        )
                    ],
                    note=_candidate_note(outcome, conflict_kind),
                )
            )

    record = LexicalFactCandidateRecord(
        schema_version=1,
        word=row.word,
        level=row.level.value,
        source_kind="curated" if row.example else "open",
        source_meaning=row.meaning,
        candidates=candidates,
        candidate_status="candidate_only",
        source_manifest_sha256=manifest_sha256,
        source=FORM_CANDIDATE_SOURCE,
        content_hash="0" * 64,
    )
    from app.ai.lexical_candidate_validation import lexical_candidate_content_hash

    return record.model_copy(
        update={"content_hash": lexical_candidate_content_hash(record)}
    )


def _fact_forms_by_role(fact: LexicalFactRecord) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for paradigm in fact.forms:
        for form in paradigm.forms:
            if form.role not in ROLE_TO_EXCHANGE:
                continue
            bucket = values.setdefault(form.role, [])
            for value in _flatten_forms((form.value,)):
                if value not in bucket:
                    bucket.append(value)
    return values


def _flatten_forms(values: Iterable[str]) -> list[str]:
    flattened: list[str] = []
    for raw in values:
        for value in raw.split("/"):
            normalized = value.strip().casefold()
            if normalized and normalized not in flattened:
                flattened.append(normalized)
    return flattened


def _compare_forms(
    word: str,
    role: str,
    current_forms: list[str],
    source_forms: list[str],
    entry: ECDICTEntry,
) -> tuple[str, str]:
    if not current_forms:
        return "source_addition", "missing_current_form"
    if set(current_forms).intersection(source_forms):
        return "source_agrees", "corroborated"
    if _orthographic_variant(current_forms, source_forms):
        return "source_conflict", "orthographic_variant_candidate"
    if _pos_mismatch(role, entry):
        return "source_conflict", "possible_pos_or_sense"
    if set(current_forms).intersection(_legacy_rule_forms(word, role)):
        return "source_conflict", "deterministic_rule_candidate"
    return "source_conflict", "source_irregular_candidate"


def _orthographic_variant(current_forms: list[str], source_forms: list[str]) -> bool:
    # The current generator's common regional ambiguity is one/two ``l`` in
    # forms such as ``traveled/travelled``.  Do not collapse every doubled
    # consonant: ``admited/admitted`` is a genuine rule failure, not a harmless
    # spelling variant.
    current_normalized = {_collapse_l(value) for value in current_forms}
    source_normalized = {_collapse_l(value) for value in source_forms}
    return bool(current_normalized.intersection(source_normalized)) and any(
        current != source
        for current in current_forms
        for source in source_forms
        if _collapse_l(current) == _collapse_l(source)
    )


def _collapse_l(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"l{2,}", "l", normalized)


def _pos_mismatch(role: str, entry: ECDICTEntry) -> bool:
    text = f"{entry.part_of_speech} {entry.translation} {entry.definition}".replace(
        "\\n", " "
    )
    tokens = set(_POS_PATTERN.findall(text.casefold()))
    if not tokens:
        return False
    if role == "plural":
        return "n" not in tokens
    if role in {
        "past",
        "past_participle",
        "present_participle",
        "third_person_singular",
    }:
        return not tokens.intersection({"v", "vt", "vi"})
    if role in {"comparative", "superlative"}:
        return not tokens.intersection({"a", "adv"})
    return False


def _legacy_rule_forms(word: str, role: str) -> set[str]:
    if role == "plural":
        if word.endswith(("s", "x", "z", "ch", "sh")):
            return {word + "es"}
        if len(word) > 1 and word.endswith("y") and word[-2] not in "aeiou":
            return {word[:-1] + "ies"}
        if word.endswith("fe"):
            return {word[:-2] + "ves"}
        if word.endswith("f") and word not in {"roof", "chief", "belief"}:
            return {word[:-1] + "ves"}
        return {word + "s"}

    if role not in {
        "past",
        "past_participle",
        "present_participle",
        "third_person_singular",
    }:
        return set()
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        third = word[:-1] + "ies"
        past = word[:-1] + "ied"
    elif word.endswith(("s", "x", "z", "ch", "sh", "o")):
        third = word + "es"
        past = word + "ed"
    else:
        third = word + "s"
        past = word + ("d" if word.endswith("e") else "ed")
    if word.endswith("e"):
        ing = word[:-1] + "ing"
    elif (
        len(word) >= 3
        and word[-1] in _CONSONANTS
        and word[-2] in "aeiou"
        and word[-3] in _CONSONANTS
    ):
        ing = word + word[-1] + "ing"
    else:
        ing = word + "ing"
    return {
        "past": {past},
        "past_participle": {past},
        "present_participle": {ing},
        "third_person_singular": {third},
    }[role]


def _candidate_note(outcome: str, conflict_kind: str) -> str:
    if outcome == "source_addition":
        return "ECDICT 提供当前范式缺少的词形；仅作候选，需人工审核。"
    if outcome == "source_agrees":
        return "ECDICT exchange 与当前词形存在重合，作为字段级佐证。"
    return {
        "orthographic_variant_candidate": (
            "当前与来源仅有重复字母差异，可能是地区拼写变体；需人工核对。"
        ),
        "possible_pos_or_sense": "来源词性与当前角色可能不一致；需人工核对词义。",
        "deterministic_rule_candidate": (
            "当前词形符合旧规则生成结果，但来源给出不同形式；禁止自动覆盖。"
        ),
        "source_irregular_candidate": "来源与当前词形不一致，需人工审核不规则形式或词义。",
    }.get(conflict_kind, "仅作候选，需人工审核。")
