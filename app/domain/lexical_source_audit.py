"""Pure coverage and conflict metrics for lexical-card source candidates."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.ai.schemas import LexicalFactRecord
from app.db.seed import VocabularySeedRow
from app.domain.lexical_source_readers import ECDICTEntry, EnglishWordnetIndex

_HEADWORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")
_FORM_CODES = frozenset({"s", "p", "d", "i", "3", "r", "t"})
_ROLE_TO_EXCHANGE = {
    "plural": "s",
    "past": "p",
    "past_participle": "d",
    "present_participle": "i",
    "third_person_singular": "3",
    "comparative": "r",
    "superlative": "t",
}


def chinese_sense_matches(source_meaning: str, labels: tuple[str, ...]) -> bool:
    source_segments = {
        _chinese_only(segment)
        for segment in _CHINESE_RUN.findall(
            unicodedata.normalize("NFKC", source_meaning)
        )
        if _chinese_only(segment)
    }
    for label in labels:
        normalized = _chinese_only(label)
        if not normalized:
            continue
        if len(normalized) == 1:
            if normalized in source_segments:
                return True
        elif any(
            normalized in segment or segment in normalized
            for segment in source_segments
            if len(segment) >= 2
        ):
            return True
    return False


def build_audit_report(
    vocabulary: list[VocabularySeedRow],
    facts: list[LexicalFactRecord],
    ecdict: dict[str, ECDICTEntry],
    exchange_codes: Counter[str],
    english: EnglishWordnetIndex,
    chinese_by_ili: dict[str, tuple[str, ...]],
    source_hashes: dict[str, str],
    *,
    manifest_hash: str,
) -> dict[str, object]:
    fact_by_word = {record.word: record for record in facts}
    ecdict_form_words = {
        word
        for word, entry in ecdict.items()
        if _FORM_CODES.intersection(entry.exchange)
    }
    missing_forms_resolvable = sum(
        word in ecdict_form_words and fact_by_word[word].status.forms == "missing"
        for word in fact_by_word
    )
    corroborated_roles = 0
    conflicting_roles = 0
    corroborated_by_role: Counter[str] = Counter()
    conflicts_by_role: Counter[str] = Counter()
    conflict_samples: list[dict[str, object]] = []
    for word, fact in fact_by_word.items():
        entry = ecdict.get(word)
        if entry is None:
            continue
        for paradigm in fact.forms:
            for form in paradigm.forms:
                code = _ROLE_TO_EXCHANGE.get(form.role)
                if code is None or code not in entry.exchange:
                    continue
                if _surface_matches(form.value, entry.exchange[code]):
                    corroborated_roles += 1
                    corroborated_by_role[form.role] += 1
                else:
                    conflicting_roles += 1
                    conflicts_by_role[form.role] += 1
                    conflict_samples.append(
                        {
                            "word": word,
                            "role": form.role,
                            "current": form.value,
                            "ecdict": list(entry.exchange[code]),
                        }
                    )

    headwords_present = 0
    words_with_relation_candidates = 0
    words_with_chinese_senses = 0
    words_with_strict_aligned_candidates = 0
    review_ready_words = 0
    sense_groups = 0
    sense_groups_with_chinese = 0
    strict_aligned_sense_groups = 0
    synonym_edges: set[tuple[str, str, str]] = set()
    antonym_edges: set[tuple[str, str, str]] = set()
    for row in vocabulary:
        senses = english.target_senses.get(row.word, [])
        if senses:
            headwords_present += 1
        word_has_candidates = False
        word_has_chinese = False
        aligned_candidate_groups = 0
        for sense in senses:
            synset = english.synsets.get(sense.synset_id)
            if synset is None:
                continue
            sense_groups += 1
            synonyms = {
                word
                for word in synset.member_words
                if word != row.word and _HEADWORD_PATTERN.fullmatch(word)
            }
            antonyms = {
                english.sense_words[target]
                for target in sense.antonym_sense_ids
                if target in english.sense_words
                and _HEADWORD_PATTERN.fullmatch(english.sense_words[target])
            }
            candidates = synonyms | antonyms
            if candidates:
                word_has_candidates = True
            labels = chinese_by_ili.get(synset.ili, ())
            if labels:
                sense_groups_with_chinese += 1
                word_has_chinese = True
            if candidates and chinese_sense_matches(row.meaning, labels):
                strict_aligned_sense_groups += 1
                aligned_candidate_groups += 1
                synonym_edges.update(
                    (row.word, sense.synset_id, target) for target in synonyms
                )
                antonym_edges.update(
                    (row.word, sense.synset_id, target) for target in antonyms
                )
        words_with_relation_candidates += word_has_candidates
        words_with_chinese_senses += word_has_chinese
        words_with_strict_aligned_candidates += aligned_candidate_groups > 0
        review_ready_words += aligned_candidate_groups == 1

    bounded_conflicts: dict[str, list[dict[str, object]]] = {}
    for item in sorted(
        conflict_samples,
        key=lambda value: (str(value["role"]), str(value["word"])),
    ):
        bucket = bounded_conflicts.setdefault(str(item["role"]), [])
        if len(bucket) < 6:
            bucket.append(item)

    total = len(vocabulary)
    return {
        "schema_version": 1,
        "mode": "candidate-only; no formal artifact or database mutation",
        "inputs": {
            "manifest_sha256": manifest_hash,
            "source_sha256": dict(sorted(source_hashes.items())),
            "vocabulary_rows": total,
            "lexical_fact_rows": len(facts),
        },
        "ecdict": {
            "target_headwords_present": len(ecdict),
            "target_headwords_missing": total - len(ecdict),
            "headwords_with_exchange": sum(
                bool(entry.exchange) for entry in ecdict.values()
            ),
            "headwords_with_form_exchange": len(ecdict_form_words),
            "missing_current_forms_with_source_candidate": missing_forms_resolvable,
            "current_form_roles_corroborated": corroborated_roles,
            "current_form_role_conflicts": conflicting_roles,
            "current_form_roles_corroborated_by_role": dict(
                sorted(corroborated_by_role.items())
            ),
            "current_form_role_conflicts_by_role": dict(
                sorted(conflicts_by_role.items())
            ),
            "current_form_conflict_samples_by_role": bounded_conflicts,
            "exchange_code_headword_counts": dict(sorted(exchange_codes.items())),
        },
        "wordnet_relations": {
            "target_headwords_present": headwords_present,
            "target_headwords_missing": total - headwords_present,
            "sense_groups": sense_groups,
            "sense_groups_with_chinese_labels": sense_groups_with_chinese,
            "strict_chinese_aligned_sense_groups": strict_aligned_sense_groups,
            "words_with_relation_candidates": words_with_relation_candidates,
            "words_with_chinese_sense_labels": words_with_chinese_senses,
            "words_with_strict_aligned_relation_candidates": (
                words_with_strict_aligned_candidates
            ),
            "words_with_one_review_ready_relation_group": review_ready_words,
            "strict_aligned_synonym_edges": len(synonym_edges),
            "strict_aligned_antonym_edges": len(antonym_edges),
        },
        "promotion_gate": {
            "forms": (
                "exact ECDICT headword + documented exchange role + no unresolved "
                "conflict; irregular/high-risk forms require sampled human audit"
            ),
            "relations": (
                "Open English WordNet synset/explicit antonym + matching ILI Chinese "
                "labels + source-meaning overlap + POS/sense grouping + human pilot"
            ),
            "missing_policy": "hide missing content; never ask an LLM to invent it",
        },
    }


def _surface_matches(current: str, source_values: tuple[str, ...]) -> bool:
    current_values = {
        value.strip().casefold() for value in current.split("/") if value.strip()
    }
    observed = {
        value.strip().casefold()
        for source in source_values
        for value in source.split("/")
        if value.strip()
    }
    return bool(current_values & observed)


def _chinese_only(value: str) -> str:
    return "".join(_CHINESE_RUN.findall(unicodedata.normalize("NFKC", value)))
