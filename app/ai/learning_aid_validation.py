"""Deterministic content and provenance validation for word learning aids."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.ai.schemas import (
    WORD_LEARNING_AIDS_PROMPT_VERSION,
    WordLearningAidGeneration,
    WordLearningAidRecord,
)

_HEADWORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
_ENGLISH_WORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*", re.IGNORECASE)
_COMMON_IRREGULAR_FORMS: dict[str, set[str]] = {
    "fling": {"flung"},
    "overtake": {"overtook", "overtaken"},
}


@dataclass(frozen=True, slots=True)
class SourceEntry:
    word: str
    level: str
    meaning: str
    example: str
    source_kind: str


@dataclass(slots=True)
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    generator_models: set[str] = field(default_factory=set)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _contains_standalone_word(example: str, word: str) -> bool:
    return (
        re.search(
            r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])",
            example,
            re.IGNORECASE,
        )
        is not None
    )


def _regular_word_forms(word: str) -> set[str]:
    """Return the headword plus deterministic, common English inflections."""
    base = word.casefold()
    forms = {base}
    if _HEADWORD_PATTERN.fullmatch(base) is None or "-" in base or "'" in base:
        return forms

    forms.update({base + "s", base + "es", base + "er", base + "est"})
    if len(base) > 1 and base.endswith("y") and base[-2] not in "aeiou":
        forms.update({base[:-1] + "ies", base[:-1] + "ied"})
    if base.endswith("e"):
        forms.update({base + "d", base[:-1] + "ing"})
    else:
        forms.update({base + "ed", base + "ing"})
    if (
        len(base) >= 3
        and base[-1] not in "aeiouwxy"
        and base[-2] in "aeiou"
        and base[-3] not in "aeiou"
    ):
        forms.update({base + base[-1] + "ed", base + base[-1] + "ing"})
    forms.update(_COMMON_IRREGULAR_FORMS.get(base, set()))
    return forms


def _contains_headword_form(text: str, word: str) -> bool:
    return any(
        re.search(
            r"(?<![A-Za-z])" + re.escape(form) + r"(?![A-Za-z])",
            text,
            re.IGNORECASE,
        )
        is not None
        for form in sorted(_regular_word_forms(word), key=len, reverse=True)
    )


def _is_obvious_inflection(base: str, candidate: str, part_of_speech: str) -> bool:
    """Reject likely grammatical forms while allowing lexicalized derivatives."""
    base_cf = base.casefold()
    candidate_cf = candidate.casefold()
    if candidate_cf == base_cf:
        return True
    if candidate_cf not in _regular_word_forms(base):
        return False

    pos = part_of_speech.casefold().strip()
    if candidate_cf in {base_cf + "s", base_cf + "es"}:
        return True
    if candidate_cf.endswith(("ied", "ed", "ing")):
        return pos.startswith("v") or "verb" in pos
    if candidate_cf.endswith(("ies",)):
        return True
    if candidate_cf.endswith(("er", "est")):
        return pos.startswith("adj") or pos in {"a.", "a"}
    return False


def validate_record(
    record: WordLearningAidRecord,
    by_word: Mapping[str, SourceEntry],
) -> list[str]:
    """Return every deterministic contract violation for one record."""
    errors: list[str] = []
    word = record.word
    source = by_word.get(word)
    if source is None:
        return [f"{word}: unknown word not present in the source CSVs"]

    if record.level != source.level:
        errors.append(f"{word}: level {record.level} != source {source.level}")
    if record.source_kind != source.source_kind:
        errors.append(
            f"{word}: source_kind {record.source_kind} != {source.source_kind}"
        )
    if _normalize_whitespace(record.source_meaning) != _normalize_whitespace(
        source.meaning
    ):
        errors.append(f"{word}: source_meaning differs from the CSV meaning")

    if source.source_kind == "curated":
        if record.example_origin != "curated":
            errors.append(f"{word}: curated example_origin must be 'curated'")
        if record.example != source.example:
            errors.append(f"{word}: curated example differs from the CSV example")
    else:
        if record.example_origin != "ai_generated":
            errors.append(f"{word}: open example_origin must be 'ai_generated'")
        example_word_count = len(_ENGLISH_WORD_PATTERN.findall(record.example))
        if not 6 <= example_word_count <= 18:
            errors.append(
                f"{word}: generated example must contain 6 to 18 English words"
            )

    # Curated examples are allowed to preserve their supplied grammatical
    # form; generated examples use the same rule so natural sentences such as
    # "the policy affected..." are not rejected merely because the model
    # inflected the target verb.  The standalone boundary still prevents
    # substring false positives (for example, ``art`` in ``article``).
    example_contains_word = _contains_headword_form(record.example, word)
    if not example_contains_word:
        errors.append(f"{word}: example does not contain the standalone headword")
    if "\n" in record.example or "\r" in record.example:
        errors.append(f"{word}: example contains a newline")
    if record.example and record.example.rstrip()[-1] not in ".?!":
        errors.append(f"{word}: example must end with . ? or !")

    seen_collocations: set[str] = set()
    for item in record.collocations:
        key = _normalize_whitespace(item.phrase).casefold()
        if key in seen_collocations:
            errors.append(f"{word}: duplicate collocation {item.phrase!r}")
        if not _contains_headword_form(item.phrase, word):
            errors.append(
                f"{word}: collocation {item.phrase!r} must contain the target word "
                "or a regular inflection"
            )
        seen_collocations.add(key)

    seen_family: set[str] = set()
    for item in record.word_family:
        member = item.word.casefold()
        if member == word.casefold():
            errors.append(f"{word}: word_family contains the target word itself")
        if _HEADWORD_PATTERN.fullmatch(member) is None:
            errors.append(f"{word}: word_family headword {item.word!r} is invalid")
        if member in seen_family:
            errors.append(f"{word}: duplicate word_family entry {item.word!r}")
        seen_family.add(member)
        if _is_obvious_inflection(word, item.word, item.part_of_speech):
            errors.append(f"{word}: word_family {item.word!r} looks like an inflection")

    if record.generator.model.casefold() == "unknown":
        errors.append(f"{word}: generator.model must not be 'unknown'")
    return errors


def sanitize_generation(
    generation: WordLearningAidGeneration,
) -> WordLearningAidGeneration:
    """Drop deterministic model noise that is safe to omit from an aid.

    Models sometimes repeat a valid family member, echo the target itself, or
    return a grammatical inflection as a family entry.  These entries convey
    no additional learning value, so removing them is safer than rejecting an
    otherwise useful record.  Invalid collocations are removed only when at
    least two valid phrases remain, preserving the schema's minimum guarantee.
    """
    word = generation.word
    family = []
    seen_family: set[str] = set()
    for item in generation.word_family:
        key = item.word.casefold()
        if key in seen_family or _is_obvious_inflection(
            word, item.word, item.part_of_speech
        ):
            continue
        seen_family.add(key)
        family.append(item)

    valid_collocations = [
        item
        for item in generation.collocations
        if _contains_headword_form(item.phrase, word)
    ]
    collocations = (
        valid_collocations
        if len(valid_collocations) >= 2
        else list(generation.collocations)
    )
    if family == list(generation.word_family) and collocations == list(
        generation.collocations
    ):
        return generation
    return generation.model_copy(
        update={"word_family": family, "collocations": collocations}
    )


def _compute_stats(records: Sequence[WordLearningAidRecord]) -> dict[str, int]:
    return {
        "total": len(records),
        "cet4": sum(1 for record in records if record.level == "CET4"),
        "cet6": sum(1 for record in records if record.level == "CET6"),
        "curated": sum(1 for record in records if record.source_kind == "curated"),
        "open": sum(1 for record in records if record.source_kind == "open"),
        "ai_generated_examples": sum(
            1 for record in records if record.example_origin == "ai_generated"
        ),
        "curated_examples": sum(
            1 for record in records if record.example_origin == "curated"
        ),
        "empty_word_family": sum(1 for record in records if not record.word_family),
    }


def validate_records(
    records: Sequence[dict[str, object]],
    ordered_sources: Sequence[SourceEntry],
    by_word: Mapping[str, SourceEntry],
    *,
    require_complete: bool,
) -> ValidationReport:
    """Validate parsed JSON objects against sources and the artifact contract."""
    errors: list[str] = []
    parsed: list[WordLearningAidRecord] = []
    for index, raw in enumerate(records, start=1):
        try:
            parsed.append(WordLearningAidRecord.model_validate(raw))
        except ValueError as exc:
            errors.append(f"line {index}: invalid record: {exc}")

    for record in parsed:
        errors.extend(validate_record(record, by_word))

    words = [record.word for record in parsed]
    duplicates = [word for word, count in Counter(words).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate words in JSONL: {sorted(duplicates)}")

    if require_complete:
        expected = [entry.word for entry in ordered_sources]
        if set(expected) != set(words):
            missing = sorted(set(expected) - set(words))
            extra = sorted(set(words) - set(expected))
            errors.append(
                f"word set mismatch: missing={len(missing)} extra={len(extra)}"
            )
        elif words != expected:
            errors.append("word order does not match the source CSV order")

    return ValidationReport(
        errors=errors,
        stats=_compute_stats(parsed),
        generator_models={record.generator.model for record in parsed},
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_provenance(
    provenance_path: Path,
    artifact_path: Path,
    report: ValidationReport,
    source_files: Mapping[str, Path],
) -> list[str]:
    """Verify provenance identity, hashes, statistics, and completion metadata."""
    if not provenance_path.is_file():
        return [f"provenance file not found: {provenance_path}"]
    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"provenance is not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["provenance root must be a JSON object"]

    errors: list[str] = []
    generator = payload.get("generator")
    if not isinstance(generator, dict):
        errors.append("provenance generator must be an object")
    else:
        if generator.get("provider") != "deepseek":
            errors.append("provenance generator.provider must be deepseek")
        if not str(generator.get("model") or "").strip():
            errors.append("provenance generator.model must not be empty")
        if generator.get("prompt_version") != WORD_LEARNING_AIDS_PROMPT_VERSION:
            errors.append("provenance prompt_version is invalid")
        if report.generator_models and report.generator_models != {
            generator.get("model")
        }:
            errors.append(
                "provenance generator model does not match every JSONL record"
            )

    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        errors.append("provenance artifact must be an object")
    else:
        if artifact.get("path") != artifact_path.name:
            errors.append("provenance artifact path does not match the JSONL")
        if artifact.get("sha256") != _sha256_file(artifact_path):
            errors.append("provenance artifact sha256 does not match the JSONL")

    recorded_sources = payload.get("source_files")
    if not isinstance(recorded_sources, dict):
        errors.append("provenance source_files must be an object")
    else:
        for name, path in source_files.items():
            if recorded_sources.get(name) != _sha256_file(path):
                errors.append(f"provenance source sha256 mismatch for {name}")

    if payload.get("stats") != report.stats:
        errors.append("provenance stats do not match validated JSONL statistics")
    if payload.get("validation") != {"result": "passed", "errors": 0}:
        errors.append("provenance validation result is not passed with zero errors")
    completed_at = payload.get("completed_at")
    try:
        completed = datetime.fromisoformat(str(completed_at))
        if completed.tzinfo is None:
            raise ValueError
    except ValueError:
        errors.append("provenance completed_at must be timezone-aware ISO-8601")
    return errors
