"""Contract tests for the candidate-only ECDICT form evidence pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.lexical_candidate_validation import (
    LexicalCandidateDataError,
    lexical_candidate_content_hash,
    load_lexical_candidate_records,
    validate_records,
)
from app.ai.lexical_source_validation import load_lexical_source_manifest
from app.db.seed import load_vocabulary_rows
from app.domain.lexical_candidate_builder import build_candidate_record
from app.domain.lexical_source_readers import ECDICTEntry
from scripts.generate_lexical_facts import build_record

ROOT = Path(__file__).resolve().parents[1]


def _rows() -> list:
    return [
        row
        for name in ("sample_words.csv", "cet_vocabulary_open.csv")
        for row in load_vocabulary_rows(ROOT / "data" / name)
    ]


def _context() -> tuple[list, list, object, str, str]:
    rows = _rows()
    facts = [build_record(row) for row in rows]
    manifest = load_lexical_source_manifest(
        ROOT / "data" / "lexical_source_manifest.json"
    )
    ecdict_source = next(
        source for source in manifest.sources if source.source_id == "ecdict"
    )
    return rows, facts, manifest, "a" * 64, ecdict_source.sha256


def test_admit_conflicts_are_classified_as_legacy_rule_candidates() -> None:
    rows, facts, _manifest, manifest_hash, source_hash = _context()
    row = next(row for row in rows if row.word == "admit")
    fact = next(fact for fact in facts if fact.word == "admit")
    entry = ECDICTEntry(
        part_of_speech="",
        translation="vt. 承认",
        definition="v. admit",
        exchange={
            "p": ("admitted",),
            "d": ("admitted",),
            "i": ("admitting",),
            "3": ("admits",),
        },
    )

    record = build_candidate_record(
        row,
        fact,
        entry,
        source_version="fixture",
        source_sha256=source_hash,
        manifest_sha256=manifest_hash,
    )

    by_role = {candidate.role: candidate for candidate in record.candidates}
    assert by_role["past"].conflict_kind == "deterministic_rule_candidate"
    assert by_role["past_participle"].outcome == "source_conflict"
    assert by_role["present_participle"].outcome == "source_agrees"
    assert record.content_hash == lexical_candidate_content_hash(record)


def test_barrel_double_letter_difference_is_not_called_irregular() -> None:
    rows, facts, _manifest, manifest_hash, source_hash = _context()
    row = next(row for row in rows if row.word == "barrel")
    fact = next(fact for fact in facts if fact.word == "barrel")
    entry = ECDICTEntry(
        part_of_speech="",
        translation="n. 桶；vt. 装入桶内",
        definition="n. container; v. put in a barrel",
        exchange={
            "s": ("barrels",),
            "p": ("barrelled",),
            "d": ("barrelled",),
            "i": ("barrelling",),
            "3": ("barrels",),
        },
    )

    record = build_candidate_record(
        row,
        fact,
        entry,
        source_version="fixture",
        source_sha256=source_hash,
        manifest_sha256=manifest_hash,
    )

    by_role = {candidate.role: candidate for candidate in record.candidates}
    assert by_role["past"].conflict_kind == "orthographic_variant_candidate"
    assert by_role["present_participle"].outcome == "source_agrees"


def test_missing_form_is_an_addition_candidate() -> None:
    rows, facts, _manifest, manifest_hash, source_hash = _context()
    row = next(row for row in rows if row.word == "adopt")
    fact = next(fact for fact in facts if fact.word == "adopt")
    entry = ECDICTEntry(
        part_of_speech="",
        translation="vt. 采用",
        definition="v. choose",
        exchange={
            "p": ("adopted",),
            "d": ("adopted",),
            "i": ("adopting",),
            "3": ("adopts",),
        },
    )

    record = build_candidate_record(
        row,
        fact,
        entry,
        source_version="fixture",
        source_sha256=source_hash,
        manifest_sha256=manifest_hash,
    )

    assert all(
        candidate.outcome == "source_addition" for candidate in record.candidates
    )
    assert all(
        candidate.conflict_kind == "missing_current_form"
        for candidate in record.candidates
    )


def test_candidate_validator_rejects_tampered_hash() -> None:
    rows, facts, manifest, manifest_hash, source_hash = _context()
    row = next(row for row in rows if row.word == "admit")
    fact = next(fact for fact in facts if fact.word == "admit")
    entry = ECDICTEntry(
        part_of_speech="",
        translation="vt. 承认",
        definition="v. admit",
        exchange={"p": ("admitted",)},
    )
    record = build_candidate_record(
        row,
        fact,
        entry,
        source_version="fixture",
        source_sha256=source_hash,
        manifest_sha256=manifest_hash,
    )
    tampered = record.model_copy(update={"content_hash": "b" * 64})
    report = validate_records(
        [tampered],
        [row],
        [fact],
        {row.word: entry},
        manifest,
        manifest_sha256=manifest_hash,
        require_complete=True,
    )
    assert any("content_hash" in error for error in report.errors)


def test_candidate_loader_rejects_empty_line(tmp_path: Path) -> None:
    path = tmp_path / "candidates.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(LexicalCandidateDataError, match="is empty"):
        load_lexical_candidate_records(path)
