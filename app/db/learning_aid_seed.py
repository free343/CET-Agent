"""Validated, idempotent import of generated word learning-aid content.

The formal artifact ``data/word_learning_aids.jsonl`` is read and validated in
full before any database write. Records are matched to existing ``Word`` rows
by headword and never create new words. Upserts skip records whose content
hash is unchanged, so repeated application startup converges without rewriting
rows or touching LearningState/FSRS data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.learning_aid_validation import (
    SourceEntry,
    validate_provenance,
    validate_records,
)
from app.ai.schemas import WordLearningAidRecord
from app.db.models import Word, WordLearningAid


class LearningAidDataError(ValueError):
    """Raised when the learning-aid JSONL is malformed or unsafe."""


def _canonical_content(record: WordLearningAidRecord) -> str:
    payload = {
        "schema_version": record.schema_version,
        "word": record.word,
        "level": record.level,
        "source_kind": record.source_kind,
        "source_meaning": record.source_meaning,
        "example": record.example,
        "example_translation": record.example_translation,
        "example_origin": record.example_origin,
        "collocations": [
            {"phrase": item.phrase, "meaning": item.meaning}
            for item in record.collocations
        ],
        "word_family": [
            {
                "word": item.word,
                "part_of_speech": item.part_of_speech,
                "meaning": item.meaning,
                "relation": item.relation,
            }
            for item in record.word_family
        ],
        "generator": record.generator.model_dump(),
        "content_status": record.content_status,
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def content_hash(record: WordLearningAidRecord) -> str:
    return hashlib.sha256(_canonical_content(record).encode("utf-8")).hexdigest()


def load_learning_aid_records(
    jsonl_path: Path,
    *,
    ordered_sources: Sequence[SourceEntry] | None = None,
    require_complete: bool = False,
    provenance_path: Path | None = None,
    source_files: Mapping[str, Path] | None = None,
) -> list[WordLearningAidRecord]:
    """Read and strictly validate the whole artifact before any write.

    A missing file is a normal, non-fatal state (the application continues
    showing the pending-generation placeholder). A present but malformed file
    raises so a partial import never reaches the database.
    """
    if not jsonl_path.exists():
        return []
    if require_complete and ordered_sources is None:
        raise ValueError("ordered_sources are required for complete validation")
    raw_records: list[dict[str, object]] = []
    with jsonl_path.open("r", encoding="utf-8", newline="") as source:
        for line_number, raw in enumerate(source, start=1):
            line = raw.rstrip("\r\n")
            if not line.strip():
                raise LearningAidDataError(
                    f"{jsonl_path.name}:{line_number} is an empty line"
                )
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LearningAidDataError(
                    f"{jsonl_path.name}:{line_number} is not valid JSON"
                ) from exc
            if not isinstance(parsed, dict):
                raise LearningAidDataError(
                    f"{jsonl_path.name}:{line_number} must be a JSON object"
                )
            raw_records.append(parsed)

    if ordered_sources is not None:
        by_word = {entry.word: entry for entry in ordered_sources}
        report = validate_records(
            raw_records,
            ordered_sources,
            by_word,
            require_complete=require_complete,
        )
        if provenance_path is not None:
            if source_files is None:
                raise ValueError("source_files are required for provenance validation")
            report.errors.extend(
                validate_provenance(
                    provenance_path,
                    jsonl_path,
                    report,
                    source_files,
                )
            )
        if report.errors:
            details = "; ".join(report.errors[:20])
            raise LearningAidDataError(
                f"{jsonl_path.name} failed validated import: {details}"
            )

    records: list[WordLearningAidRecord] = []
    for line_number, payload in enumerate(raw_records, start=1):
        try:
            records.append(WordLearningAidRecord.model_validate(payload))
        except Exception as exc:
            raise LearningAidDataError(
                f"{jsonl_path.name}:{line_number} violates the record contract: {exc}"
            ) from exc
    return records


def seed_learning_aids(
    session: Session,
    records: Sequence[WordLearningAidRecord],
) -> int:
    """Upsert validated records matched to existing words; returns rows written."""
    word_ids = {
        word: word_id
        for word, word_id in session.execute(select(Word.word, Word.id)).all()
    }
    written = 0
    for record in records:
        word_id = word_ids.get(record.word)
        if word_id is None:
            # The import must never create a new word; unknown headwords are
            # skipped rather than inventing vocabulary outside the CSV gate.
            continue
        aid = session.get(WordLearningAid, word_id)
        record_hash = content_hash(record)
        if aid is not None and aid.content_hash == record_hash:
            continue
        if aid is None:
            aid = WordLearningAid(word_id=word_id)
            session.add(aid)
        aid.example = record.example
        aid.example_translation = record.example_translation
        aid.collocations_json = json.dumps(
            [item.model_dump() for item in record.collocations],
            ensure_ascii=False,
        )
        aid.word_family_json = json.dumps(
            [item.model_dump() for item in record.word_family],
            ensure_ascii=False,
        )
        aid.generator = record.generator.provider
        aid.model = record.generator.model
        aid.prompt_version = record.generator.prompt_version
        aid.content_status = record.content_status
        aid.content_hash = record_hash
        written += 1
    session.flush()
    return written
