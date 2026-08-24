"""Offline validation for the adaptive lexical-fact JSONL artifact."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.schemas import LexicalFactRecord
from app.db.seed import VocabularySeedRow

_HEADWORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
_SURFACE_FORM_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*(?:/[a-z]+(?:[-'][a-z]+)*)*")


@dataclass(slots=True)
class LexicalFactValidationReport:
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


class LexicalFactDataError(ValueError):
    """Raised when a lexical-fact artifact is malformed or incomplete."""


def _canonical_payload(record: LexicalFactRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "word": record.word,
        "level": record.level,
        "source_kind": record.source_kind,
        "source_meaning": record.source_meaning,
        "forms": [
            paradigm.model_dump(mode="json", by_alias=True) for paradigm in record.forms
        ],
        "relations": [group.model_dump(mode="json") for group in record.relations],
        "status": record.status.model_dump(mode="json"),
        "source": record.source,
    }


def lexical_fact_content_hash(record: LexicalFactRecord) -> str:
    canonical = json.dumps(
        _canonical_payload(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_record(
    record: LexicalFactRecord,
    source: VocabularySeedRow | None,
) -> list[str]:
    errors: list[str] = []
    if source is None:
        return [f"{record.word}: unknown word not present in vocabulary sources"]
    if record.level != source.level.value:
        errors.append(f"{record.word}: level differs from vocabulary source")
    expected_kind = "curated" if source.example else "open"
    if record.source_kind != expected_kind:
        errors.append(f"{record.word}: source_kind differs from vocabulary source")
    if record.source_meaning.strip() != source.meaning.strip():
        errors.append(f"{record.word}: source_meaning differs from vocabulary source")
    if record.content_hash != lexical_fact_content_hash(record):
        errors.append(f"{record.word}: content_hash does not match canonical content")
    if record.status.forms == "verified_empty" and record.forms:
        errors.append(f"{record.word}: verified_empty forms cannot contain paradigms")
    if record.status.relations == "verified_empty" and record.relations:
        errors.append(
            f"{record.word}: verified_empty relations cannot contain relation groups"
        )
    seen_values: set[tuple[str, str]] = set()
    for paradigm in record.forms:
        for form in paradigm.forms:
            value = form.value.casefold().strip()
            key = (form.role, value)
            if not value or _SURFACE_FORM_PATTERN.fullmatch(value) is None:
                errors.append(f"{record.word}: invalid lexical form {form.value!r}")
            if key in seen_values:
                errors.append(f"{record.word}: duplicate lexical form {form.value!r}")
            seen_values.add(key)
    seen_relation_groups: set[tuple[str, str, str]] = set()
    for group in record.relations:
        group_key = (group.relation_type, group.part_of_speech, group.sense)
        if group_key in seen_relation_groups:
            errors.append(f"{record.word}: duplicate relation group {group_key!r}")
        seen_relation_groups.add(group_key)
        seen_items: set[str] = set()
        for item in group.items:
            relation_key = item.word.casefold().strip()
            if _HEADWORD_PATTERN.fullmatch(relation_key) is None:
                errors.append(f"{record.word}: invalid relation target {item.word!r}")
            if relation_key == record.word.casefold():
                errors.append(f"{record.word}: relation target repeats the headword")
            if relation_key in seen_items:
                errors.append(f"{record.word}: duplicate relation target {item.word!r}")
            seen_items.add(relation_key)
    return errors


def validate_records(
    records: Sequence[LexicalFactRecord],
    sources: Sequence[VocabularySeedRow],
    *,
    require_complete: bool = False,
) -> LexicalFactValidationReport:
    report = LexicalFactValidationReport()
    source_by_word = {row.word: row for row in sources}
    seen: set[str] = set()
    for record in records:
        if record.word in seen:
            report.errors.append(f"duplicate lexical fact record: {record.word}")
        seen.add(record.word)
        report.errors.extend(validate_record(record, source_by_word.get(record.word)))
    if require_complete:
        expected = set(source_by_word)
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        if missing:
            report.errors.append(
                f"missing lexical fact records: {', '.join(missing[:12])}"
            )
        if extra:
            report.errors.append(
                f"unknown lexical fact records: {', '.join(extra[:12])}"
            )
        if len(records) != len(expected):
            report.errors.append(
                f"record count {len(records)} does not equal source count {len(expected)}"
            )
    report.stats = {
        "total": len(records),
        "forms_present": sum(bool(record.forms) for record in records),
        "relations_present": sum(bool(record.relations) for record in records),
        "source_validated_forms": sum(
            record.status.forms == "source_validated" for record in records
        ),
        "missing_forms": sum(record.status.forms == "missing" for record in records),
        "verified_empty_forms": sum(
            record.status.forms == "verified_empty" for record in records
        ),
        "source_validated_relations": sum(
            record.status.relations == "source_validated" for record in records
        ),
    }
    return report


def load_lexical_fact_records(
    jsonl_path: Path,
    *,
    sources: Sequence[VocabularySeedRow] | None = None,
    require_complete: bool = False,
) -> list[LexicalFactRecord]:
    """Read/validate the whole artifact before any database mutation."""
    if not jsonl_path.exists():
        return []
    raw_records: list[LexicalFactRecord] = []
    with jsonl_path.open("r", encoding="utf-8", newline="") as source:
        for line_number, raw in enumerate(source, start=1):
            if not raw.strip():
                raise LexicalFactDataError(f"{jsonl_path.name}:{line_number} is empty")
            try:
                payload = json.loads(raw)
                record = LexicalFactRecord.model_validate(payload)
            except Exception as exc:
                raise LexicalFactDataError(
                    f"{jsonl_path.name}:{line_number} violates the lexical-fact contract"
                ) from exc
            raw_records.append(record)
    if sources is not None:
        report = validate_records(
            raw_records, sources, require_complete=require_complete
        )
        if report.errors:
            raise LexicalFactDataError(
                f"{jsonl_path.name} failed validation: {'; '.join(report.errors[:20])}"
            )
    return raw_records
