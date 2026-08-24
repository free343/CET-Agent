"""Contract tests for the candidate-only WordNet/COW relation pilot."""

from __future__ import annotations

from pathlib import Path

from app.ai.lexical_relation_candidate_validation import (
    lexical_relation_candidate_content_hash,
    validate_records,
)
from app.ai.lexical_source_validation import load_lexical_source_manifest
from app.db.seed import load_vocabulary_rows
from app.domain.lexical_relation_candidate_builder import (
    build_relation_candidate_record,
)
from app.domain.lexical_source_readers import (
    ECDICTEntry,
    EnglishWordnetIndex,
    SenseData,
    SynsetData,
)

ROOT = Path(__file__).resolve().parents[1]


def test_single_aligned_synonym_keeps_frequency_and_field_evidence() -> None:
    row = next(
        row
        for row in load_vocabulary_rows(ROOT / "data" / "cet_vocabulary_open.csv")
        if row.word == "main"
    )
    manifest = load_lexical_source_manifest(
        ROOT / "data" / "lexical_source_manifest.json"
    )
    contracts = {source.source_id: source for source in manifest.sources}
    ecdict = {
        "main": ECDICTEntry("", "a. 主要的", "a. important", {}, 888),
        "primary": ECDICTEntry("", "a. 主要的", "a. first", {}, 1504),
    }
    english = EnglishWordnetIndex(
        target_senses={"main": [SenseData("syn-main", "a", (), "main-sense")]},
        sense_words={"main-sense": "main"},
        sense_synsets={"main-sense": "syn-main"},
        synsets={
            "syn-main": SynsetData("i-main", "most important", ("main", "primary"))
        },
    )

    record = build_relation_candidate_record(
        row,
        english,
        {"i-main": ("主要的",)},
        ecdict,
        oewn_version=contracts["oewn-2025"].version,
        oewn_sha256=contracts["oewn-2025"].sha256,
        cow_version=contracts["omw-cmn-2"].version,
        cow_sha256=contracts["omw-cmn-2"].sha256,
        ecdict_version=contracts["ecdict"].version,
        ecdict_sha256=contracts["ecdict"].sha256,
        manifest_sha256="a" * 64,
    )

    assert record.selection_status == "selected_single_sense"
    assert record.groups[0].items[0].word == "primary"
    assert record.groups[0].items[0].frequency == 1504
    assert record.content_hash == lexical_relation_candidate_content_hash(record)
    report = validate_records(
        [record],
        [row],
        ecdict,
        english,
        {"i-main": ("主要的",)},
        manifest,
        manifest_sha256="a" * 64,
        require_complete=True,
    )
    assert report.errors == []


def test_relation_pilot_rejects_unaligned_sense() -> None:
    row = next(
        row
        for row in load_vocabulary_rows(ROOT / "data" / "cet_vocabulary_open.csv")
        if row.word == "main"
    )
    manifest = load_lexical_source_manifest(
        ROOT / "data" / "lexical_source_manifest.json"
    )
    contracts = {source.source_id: source for source in manifest.sources}
    english = EnglishWordnetIndex(
        target_senses={"main": [SenseData("syn-main", "a", (), "main-sense")]},
        sense_words={"main-sense": "main"},
        sense_synsets={"main-sense": "syn-main"},
        synsets={
            "syn-main": SynsetData("i-main", "most important", ("main", "primary"))
        },
    )
    ecdict = {
        "main": ECDICTEntry("", "a. 主要的", "a. important", {}, 888),
        "primary": ECDICTEntry("", "a. 主要的", "a. first", {}, 1504),
    }
    record = build_relation_candidate_record(
        row,
        english,
        {"i-main": ("公司",)},
        ecdict,
        oewn_version=contracts["oewn-2025"].version,
        oewn_sha256=contracts["oewn-2025"].sha256,
        cow_version=contracts["omw-cmn-2"].version,
        cow_sha256=contracts["omw-cmn-2"].sha256,
        ecdict_version=contracts["ecdict"].version,
        ecdict_sha256=contracts["ecdict"].sha256,
        manifest_sha256="a" * 64,
    )
    assert record.selection_status == "no_aligned_sense"
    assert record.groups == []
