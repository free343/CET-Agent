"""Independent, offline, repeatable validator for word learning aids."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.learning_aid_validation import (
    SourceEntry,
    ValidationReport,
    validate_provenance,
    validate_records,
)
from app.ai.learning_aid_validation import validate_record as _validate_record

validate_record = _validate_record

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CURATED_CSV = PROJECT_ROOT / "data" / "sample_words.csv"
OPEN_CSV = PROJECT_ROOT / "data" / "cet_vocabulary_open.csv"
DEFAULT_JSONL = PROJECT_ROOT / "data" / "word_learning_aids.jsonl"
DEFAULT_PROVENANCE = PROJECT_ROOT / "data" / "word_learning_aids.provenance.json"


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
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{jsonl_path.name}:{line_number} is not valid JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise TypeError(
                    f"{jsonl_path.name}:{line_number} must be a JSON object"
                )
            records.append(payload)
    return records


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
        help="require the exact full 4,611-word source set and valid provenance",
    )
    parser.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    parser.add_argument(
        "--provenance",
        default=None,
        help="provenance path; defaults beside --jsonl when completeness is required",
    )
    args = parser.parse_args(argv)

    jsonl_path = Path(args.jsonl).resolve()
    if not jsonl_path.exists():
        print(f"ERROR: {jsonl_path} not found", file=sys.stderr)
        return 2
    ordered, by_word = load_sources()
    try:
        records = read_records(jsonl_path)
    except (TypeError, ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = validate_records(
        records,
        ordered,
        by_word,
        require_complete=args.require_complete,
    )
    if args.require_complete:
        provenance_path = (
            Path(args.provenance).resolve()
            if args.provenance
            else jsonl_path.with_name(DEFAULT_PROVENANCE.name)
        )
        report.errors.extend(
            validate_provenance(
                provenance_path,
                jsonl_path,
                report,
                {CURATED_CSV.name: CURATED_CSV, OPEN_CSV.name: OPEN_CSV},
            )
        )
    _print_report(report)
    for error in report.errors[:50]:
        print(f"  - {error}")
    if len(report.errors) > 50:
        print(f"  ... and {len(report.errors) - 50} more errors")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
