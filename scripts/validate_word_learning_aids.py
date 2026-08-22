"""Independent, offline, repeatable strict validator for word learning aids.

This script never touches the database or the network. It cross-checks the
formal JSONL against the two source CSVs and enforces the full artifact
contract. Exit code 0 means every requested check passed; any error exits
non-zero.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.schemas import WordLearningAidRecord

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CURATED_CSV = PROJECT_ROOT / "data" / "sample_words.csv"
OPEN_CSV = PROJECT_ROOT / "data" / "cet_vocabulary_open.csv"
DEFAULT_JSONL = PROJECT_ROOT / "data" / "word_learning_aids.jsonl"

_HEADWORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
_INFLECTION_SUFFIXES = ("s", "es", "ed", "ing", "er", "est")


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


def _read_csv(path: Path, source_kind: str) -> list[SourceEntry]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return [
            SourceEntry(
                word=(row.get("word") or "").strip().lower(),
                level=(row.get("level") or "").strip().upper(),
                meaning=(row.get("meaning") or "").strip(),
                example=(row.get("example") or "").strip(),
                source_kind=source_kind,
            )
            for row in reader
        ]


def load_sources() -> tuple[list[SourceEntry], dict[str, SourceEntry]]:
    curated = _read_csv(CURATED_CSV, "curated")
    open_entries = _read_csv(OPEN_CSV, "open")
    ordered = curated + open_entries
    return ordered, {entry.word: entry for entry in ordered}


def read_records(jsonl_path: Path) -> list[dict[str, object]]:
    """Parse one JSON object per physical line; raise on malformed input."""
    if not jsonl_path.exists():
        raise FileNotFoundError(f"Learning-aid JSONL not found: {jsonl_path}")
    records: list[dict[str, object]] = []
    with jsonl_path.open("r", encoding="utf-8", newline="") as source:
        for line_number, raw in enumerate(source, start=1):
            line = raw.rstrip("\r\n")
            if not line.strip():
                raise ValueError(f"{jsonl_path.name}:{line_number} is an empty line")
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{jsonl_path.name}:{line_number} is not valid JSON"
                ) from exc
    return records


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


def _is_obvious_inflection(base: str, candidate: str) -> bool:
    base_cf = base.casefold()
    candidate_cf = candidate.casefold()
    if candidate_cf == base_cf:
        return True
    return any(candidate_cf == base_cf + suffix for suffix in _INFLECTION_SUFFIXES)


def validate_record(
    record: WordLearningAidRecord,
    by_word: dict[str, SourceEntry],
) -> list[str]:
    """Return every contract violation for one assembled record."""
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
        if not record.example.strip():
            errors.append(f"{word}: open example must not be empty")

    if not _contains_standalone_word(record.example, word):
        errors.append(f"{word}: example does not contain the standalone headword")
    if "\n" in record.example or "\r" in record.example:
        errors.append(f"{word}: example contains a newline")
    if record.example and record.example.rstrip()[-1] not in ".?!":
        errors.append(f"{word}: example must end with . ? or !")

    seen_collocations: set[str] = set()
    for item in record.collocations:
        key = _normalize_whitespace(item.phrase).casefold()
        if not key:
            errors.append(f"{word}: collocation phrase is empty")
        elif key in seen_collocations:
            errors.append(f"{word}: duplicate collocation {item.phrase!r}")
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
        if _is_obvious_inflection(word, item.word):
            errors.append(f"{word}: word_family {item.word!r} looks like an inflection")

    if record.generator.model.casefold() == "unknown":
        errors.append(f"{word}: generator.model must not be 'unknown'")

    return errors


def _compute_stats(records: list[WordLearningAidRecord]) -> dict[str, int]:
    return {
        "total": len(records),
        "cet4": sum(1 for r in records if r.level == "CET4"),
        "cet6": sum(1 for r in records if r.level == "CET6"),
        "curated": sum(1 for r in records if r.source_kind == "curated"),
        "open": sum(1 for r in records if r.source_kind == "open"),
        "ai_generated_examples": sum(
            1 for r in records if r.example_origin == "ai_generated"
        ),
        "curated_examples": sum(1 for r in records if r.example_origin == "curated"),
        "empty_word_family": sum(1 for r in records if not r.word_family),
    }


def validate_records(
    records: list[dict[str, object]],
    ordered_sources: list[SourceEntry],
    by_word: dict[str, SourceEntry],
    *,
    require_complete: bool,
) -> ValidationReport:
    """Validate parsed records against the source CSVs and the contract."""
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
        actual = words
        if set(expected) != set(actual):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            errors.append(
                f"word set mismatch: missing={len(missing)} extra={len(extra)}"
            )
        elif actual != expected:
            errors.append("word order does not match the source CSV order")

    return ValidationReport(errors=errors, stats=_compute_stats(parsed))


def _print_report(report: ValidationReport) -> None:
    stats = report.stats
    print(
        f"total={stats.get('total', 0)} "
        f"cet4={stats.get('cet4', 0)} cet6={stats.get('cet6', 0)} "
        f"curated={stats.get('curated', 0)} open={stats.get('open', 0)}"
    )
    print(
        f"ai_generated_examples={stats.get('ai_generated_examples', 0)} "
        f"curated_examples={stats.get('curated_examples', 0)} "
        f"empty_word_family={stats.get('empty_word_family', 0)}"
    )
    print(f"errors={len(report.errors)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strict offline validator for data/word_learning_aids.jsonl"
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="require the exact full 4,611-word source set in source order",
    )
    parser.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    args = parser.parse_args(argv)

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.exists():
        print(f"ERROR: {jsonl_path} not found", file=sys.stderr)
        return 2
    ordered, by_word = load_sources()
    try:
        records = read_records(jsonl_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = validate_records(
        records,
        ordered,
        by_word,
        require_complete=args.require_complete,
    )
    _print_report(report)
    for error in report.errors[:50]:
        print(f"  - {error}")
    if len(report.errors) > 50:
        print(f"  ... and {len(report.errors) - 50} more errors")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
