"""Strict validation for source-backed WordNet/COW relation evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.ai.schemas import (
    LexicalRelationCandidateRecord,
    LexicalSourceManifest,
)
from app.db.seed import VocabularySeedRow
from app.domain.lexical_relation_candidate_builder import (
    MAX_RELATION_TARGET_FREQUENCY,
    RELATION_CANDIDATE_SOURCE,
)
from app.domain.lexical_relation_quality import learner_translation
from app.domain.lexical_source_readers import ECDICTEntry, EnglishWordnetIndex


class LexicalRelationCandidateDataError(ValueError):
    """Raised when relation candidate evidence is malformed or inconsistent."""


@dataclass(slots=True)
class LexicalRelationCandidateValidationReport:
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _canonical_payload(record: LexicalRelationCandidateRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "word": record.word,
        "level": record.level,
        "source_kind": record.source_kind,
        "source_meaning": record.source_meaning,
        "groups": [group.model_dump(mode="json") for group in record.groups],
        "selection_status": record.selection_status,
        "candidate_status": record.candidate_status,
        "source_manifest_sha256": record.source_manifest_sha256,
        "source": record.source,
    }


def lexical_relation_candidate_content_hash(
    record: LexicalRelationCandidateRecord,
) -> str:
    canonical = json.dumps(
        _canonical_payload(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_record(
    record: LexicalRelationCandidateRecord,
    source: VocabularySeedRow | None,
    ecdict: dict[str, ECDICTEntry],
    english: EnglishWordnetIndex,
    chinese_by_ili: dict[str, tuple[str, ...]],
    manifest: LexicalSourceManifest,
    *,
    manifest_sha256: str,
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
    if record.source != RELATION_CANDIDATE_SOURCE:
        errors.append(f"{record.word}: unexpected relation candidate source identifier")
    if record.candidate_status != "candidate_only":
        errors.append(f"{record.word}: candidate_status must remain candidate_only")
    if record.source_manifest_sha256 != manifest_sha256:
        errors.append(f"{record.word}: source manifest hash does not match")
    if record.content_hash != lexical_relation_candidate_content_hash(record):
        errors.append(f"{record.word}: content_hash does not match canonical content")
    selected_statuses = {
        "selected_single_sense",
        "selected_aligned_senses",
        "truncated_aligned_senses",
    }
    if record.selection_status not in selected_statuses and record.groups:
        errors.append(
            f"{record.word}: excluded relation candidate cannot contain groups"
        )
    if record.selection_status in selected_statuses and not record.groups:
        errors.append(
            f"{record.word}: selected relation candidate must contain a group"
        )

    source_by_id = {item.source_id: item for item in manifest.sources}
    for group in record.groups:
        synset = english.synsets.get(group.synset_id)
        if synset is None:
            errors.append(f"{record.word}: unknown OEWN synset {group.synset_id}")
            continue
        if synset.ili != group.ili:
            errors.append(f"{record.word}:{group.synset_id}: ILI differs")
        labels = chinese_by_ili.get(group.ili, ())
        if not labels or group.sense not in _compact_label_options(labels):
            errors.append(f"{record.word}:{group.synset_id}: COW sense labels differ")
        seen_items: set[str] = set()
        for item in group.items:
            if item.word in seen_items:
                errors.append(
                    f"{record.word}:{group.synset_id}: duplicate relation target"
                )
            seen_items.add(item.word)
            entry = ecdict.get(item.word)
            if entry is None:
                errors.append(
                    f"{record.word}: relation target is outside ECDICT pilot set"
                )
            elif item.frequency != entry.frequency:
                errors.append(f"{record.word}:{item.word}: frequency differs")
            else:
                expected_meaning = learner_translation(
                    entry.translation,
                    part_of_speech=group.part_of_speech,
                )
                if not expected_meaning:
                    errors.append(
                        f"{record.word}:{item.word}: ECDICT translation is domain-only"
                    )
                elif item.meaning != expected_meaning:
                    errors.append(f"{record.word}:{item.word}: translation differs")
            if item.frequency <= 0 or item.frequency > MAX_RELATION_TARGET_FREQUENCY:
                errors.append(
                    f"{record.word}:{item.word}: frequency is outside pilot bound"
                )
            if item.word == record.word:
                errors.append(f"{record.word}: relation target repeats headword")
            if (
                group.relation_type == "synonym"
                and item.word not in synset.member_words
            ):
                errors.append(
                    f"{record.word}:{item.word}: synonym is not a synset member"
                )
            if group.relation_type == "antonym" and not _is_explicit_antonym(
                record.word, group.synset_id, item.word, english
            ):
                errors.append(f"{record.word}:{item.word}: antonym is not explicit")
            if item.english_definition != synset.definition[:160]:
                errors.append(f"{record.word}:{item.word}: definition differs")
            _validate_evidence(
                record.word,
                group.relation_type,
                group.synset_id,
                group.ili,
                item.word,
                item.evidence,
                source_by_id,
                errors,
            )
    return errors


def validate_records(
    records: Sequence[LexicalRelationCandidateRecord],
    sources: Sequence[VocabularySeedRow],
    ecdict: dict[str, ECDICTEntry],
    english: EnglishWordnetIndex,
    chinese_by_ili: dict[str, tuple[str, ...]],
    manifest: LexicalSourceManifest,
    *,
    manifest_sha256: str,
    require_complete: bool = False,
) -> LexicalRelationCandidateValidationReport:
    report = LexicalRelationCandidateValidationReport()
    source_by_word = {row.word: row for row in sources}
    seen: set[str] = set()
    for record in records:
        if record.word in seen:
            report.errors.append(f"duplicate relation candidate record: {record.word}")
        seen.add(record.word)
        report.errors.extend(
            validate_record(
                record,
                source_by_word.get(record.word),
                ecdict,
                english,
                chinese_by_ili,
                manifest,
                manifest_sha256=manifest_sha256,
            )
        )
    if require_complete:
        expected = set(source_by_word)
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        if missing:
            report.errors.append(
                f"missing relation candidate records: {', '.join(missing[:12])}"
            )
        if extra:
            report.errors.append(
                f"unknown relation candidate records: {', '.join(extra[:12])}"
            )
        if len(records) != len(expected):
            report.errors.append(
                f"record count {len(records)} does not equal source count {len(expected)}"
            )

    relation_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    target_words: set[str] = set()
    for record in records:
        status_counts[record.selection_status] += 1
        for group in record.groups:
            relation_counts[group.relation_type] += 1
            target_words.update(item.word for item in group.items)
    report.stats = {
        "total": len(records),
        "selected_single_sense": status_counts["selected_single_sense"],
        "selected_aligned_senses": status_counts["selected_aligned_senses"],
        "truncated_aligned_senses": status_counts["truncated_aligned_senses"],
        "excluded_multiple_senses": status_counts["excluded_multiple_senses"],
        "no_aligned_sense": status_counts["no_aligned_sense"],
        "groups": sum(len(record.groups) for record in records),
        "items": sum(len(group.items) for record in records for group in record.groups),
        "synonym_groups": relation_counts["synonym"],
        "antonym_groups": relation_counts["antonym"],
        "unique_relation_targets": len(target_words),
    }
    return report


def load_lexical_relation_candidate_records(
    jsonl_path: Path,
    *,
    sources: Sequence[VocabularySeedRow] | None = None,
    ecdict: dict[str, ECDICTEntry] | None = None,
    english: EnglishWordnetIndex | None = None,
    chinese_by_ili: dict[str, tuple[str, ...]] | None = None,
    manifest: LexicalSourceManifest | None = None,
    manifest_sha256: str | None = None,
    require_complete: bool = False,
) -> list[LexicalRelationCandidateRecord]:
    if not jsonl_path.exists():
        return []
    records: list[LexicalRelationCandidateRecord] = []
    with jsonl_path.open("r", encoding="utf-8", newline="") as source:
        for line_number, raw in enumerate(source, start=1):
            if not raw.strip():
                raise LexicalRelationCandidateDataError(
                    f"{jsonl_path.name}:{line_number} is empty"
                )
            try:
                records.append(
                    LexicalRelationCandidateRecord.model_validate(json.loads(raw))
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                raise LexicalRelationCandidateDataError(
                    f"{jsonl_path.name}:{line_number} violates the relation candidate contract"
                ) from exc
    context = (sources, ecdict, english, chinese_by_ili, manifest, manifest_sha256)
    if all(value is None for value in context):
        return records
    if any(value is None for value in context):
        raise LexicalRelationCandidateDataError(
            "relation validation requires all source, ECDICT, WordNet, COW, and manifest inputs"
        )
    assert sources is not None
    assert ecdict is not None
    assert english is not None
    assert chinese_by_ili is not None
    assert manifest is not None
    assert manifest_sha256 is not None
    report = validate_records(
        records,
        sources,
        ecdict,
        english,
        chinese_by_ili,
        manifest,
        manifest_sha256=manifest_sha256,
        require_complete=require_complete,
    )
    if report.errors:
        raise LexicalRelationCandidateDataError(
            f"{jsonl_path.name} failed validation: {'; '.join(report.errors[:20])}"
        )
    return records


def load_runtime_lexical_relation_candidates(
    jsonl_path: Path,
    provenance_path: Path,
    *,
    expected_words: set[str] | None = None,
    manifest_path: Path | None = None,
) -> list[LexicalRelationCandidateRecord]:
    """Load the packaged candidate overlay without downloading source files.

    The offline validator performs the expensive source replay.  Startup still
    repeats the artifact hash, canonical record hash, complete-word-set, and
    provenance checks before candidate data can enter SQLite.  This keeps a
    packaged/stale/partially copied artifact from silently becoming learner
    content while avoiding network or dictionary access in the desktop app.
    """
    if not jsonl_path.exists():
        return []
    try:
        records = load_lexical_relation_candidate_records(jsonl_path)
    except (OSError, LexicalRelationCandidateDataError) as exc:
        raise LexicalRelationCandidateDataError(str(exc)) from exc

    seen: set[str] = set()
    for record in records:
        if record.word in seen:
            raise LexicalRelationCandidateDataError(
                f"duplicate runtime relation candidate record: {record.word}"
            )
        seen.add(record.word)
        if record.candidate_status != "candidate_only":
            raise LexicalRelationCandidateDataError(
                f"{record.word}: runtime candidate status is not candidate_only"
            )
        if record.source != RELATION_CANDIDATE_SOURCE:
            raise LexicalRelationCandidateDataError(
                f"{record.word}: unexpected runtime candidate source"
            )
        if record.content_hash != lexical_relation_candidate_content_hash(record):
            raise LexicalRelationCandidateDataError(
                f"{record.word}: runtime candidate content hash does not match"
            )

    if expected_words is not None:
        observed = set(seen)
        missing = sorted(expected_words - observed)
        extra = sorted(observed - expected_words)
        if missing or extra or len(records) != len(expected_words):
            detail: list[str] = []
            if missing:
                detail.append(f"missing={', '.join(missing[:8])}")
            if extra:
                detail.append(f"extra={', '.join(extra[:8])}")
            detail.append(f"rows={len(records)} expected={len(expected_words)}")
            raise LexicalRelationCandidateDataError(
                "runtime relation candidate word set mismatch: " + "; ".join(detail)
            )

    _validate_runtime_candidate_provenance(
        provenance_path,
        jsonl_path,
        manifest_path=manifest_path,
        record_count=len(records),
        stats=_runtime_candidate_stats(records),
    )
    return records


def _runtime_candidate_stats(
    records: Sequence[LexicalRelationCandidateRecord],
) -> dict[str, int]:
    relation_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    targets: set[str] = set()
    groups = 0
    items = 0
    for record in records:
        status_counts[record.selection_status] += 1
        groups += len(record.groups)
        for group in record.groups:
            relation_counts[group.relation_type] += 1
            items += len(group.items)
            targets.update(item.word for item in group.items)
    return {
        "total": len(records),
        "selected_single_sense": status_counts["selected_single_sense"],
        "selected_aligned_senses": status_counts["selected_aligned_senses"],
        "truncated_aligned_senses": status_counts["truncated_aligned_senses"],
        "excluded_multiple_senses": status_counts["excluded_multiple_senses"],
        "no_aligned_sense": status_counts["no_aligned_sense"],
        "groups": groups,
        "items": items,
        "synonym_groups": relation_counts["synonym"],
        "antonym_groups": relation_counts["antonym"],
        "unique_relation_targets": len(targets),
    }


def _validate_runtime_candidate_provenance(
    provenance_path: Path,
    jsonl_path: Path,
    *,
    manifest_path: Path | None,
    record_count: int,
    stats: dict[str, int],
) -> None:
    if not provenance_path.exists():
        raise LexicalRelationCandidateDataError(
            "runtime relation candidate provenance file is missing"
        )
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance.get("schema_version") != 1:
            raise ValueError("unsupported provenance schema")
        if provenance.get("candidate_status") != "candidate_only":
            raise ValueError("candidate status is not candidate_only")
        artifact = provenance["artifact"]
        if artifact["file"] != jsonl_path.name:
            raise ValueError("provenance artifact filename does not match")
        if artifact["sha256"] != _digest(jsonl_path):
            raise ValueError("provenance artifact hash does not match")
        if int(artifact["rows"]) != record_count:
            raise ValueError("provenance row count does not match")
        expected_stats = dict(artifact["counts"])
        # Older pilot files did not include the explicit multi-sense counters;
        # the current expanded artifact does.  Compare only keys that exist in
        # the artifact while still rejecting a changed value.
        for key, value in expected_stats.items():
            if stats.get(key) != value:
                raise ValueError(f"provenance count does not match: {key}")
        if manifest_path is not None:
            source_manifest = provenance["source_manifest"]
            if source_manifest["file"] != manifest_path.name:
                raise ValueError("provenance manifest filename does not match")
            if source_manifest["sha256"] != _digest(manifest_path):
                raise ValueError("provenance manifest hash does not match")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise LexicalRelationCandidateDataError(
            f"invalid runtime relation-candidate provenance: {exc}"
        ) from exc


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_evidence(
    word: str,
    relation_type: str,
    synset_id: str,
    ili: str,
    target_word: str,
    evidence: list,
    source_by_id: dict,
    errors: list[str],
) -> None:
    if len(evidence) != 3:
        errors.append(
            f"{word}:{target_word}: exactly three evidence pointers are required"
        )
        return
    seen: set[str] = set()
    for pointer in evidence:
        if pointer.source_id in seen:
            errors.append(f"{word}:{target_word}: duplicate evidence source")
        seen.add(pointer.source_id)
        contract = source_by_id.get(pointer.source_id)
        if contract is None:
            errors.append(f"{word}:{target_word}: evidence source is not in manifest")
            continue
        if pointer.source_version != contract.version:
            errors.append(f"{word}:{target_word}: evidence version differs")
        if pointer.source_sha256 != contract.sha256:
            errors.append(f"{word}:{target_word}: evidence hash differs")
        if pointer.source_id == "oewn-2025":
            expected_field = (
                "synset.members" if relation_type == "synonym" else "sense.antonym"
            )
            if pointer.field != expected_field:
                errors.append(f"{word}:{target_word}: OEWN evidence field differs")
            expected_locator = (
                f"english-wordnet-2025.xml.gz:synset={synset_id}"
                if relation_type == "synonym"
                else "english-wordnet-2025.xml.gz:sense="
            )
            if not pointer.locator.startswith(expected_locator):
                errors.append(f"{word}:{target_word}: OEWN evidence locator differs")
        elif pointer.source_id == "omw-cmn-2":
            if (
                pointer.field != "synset.labels"
                or pointer.locator != f"omw-cmn.xml:ili={ili}"
            ):
                errors.append(f"{word}:{target_word}: COW evidence locator differs")
        elif pointer.source_id == "ecdict":
            if (
                pointer.field != "translation"
                or pointer.locator != f"ecdict.csv:word={target_word}:field=translation"
            ):
                errors.append(f"{word}:{target_word}: ECDICT evidence locator differs")


def _is_explicit_antonym(
    headword: str,
    synset_id: str,
    target_word: str,
    english: EnglishWordnetIndex,
) -> bool:
    target_ids = {
        target
        for sense in english.target_senses.get(headword, [])
        if sense.synset_id == synset_id
        for target in sense.antonym_sense_ids
        if english.sense_words.get(target) == target_word
    }
    return bool(target_ids)


def _compact_label_options(labels: tuple[str, ...]) -> set[str]:
    return {
        "；".join(label.strip() for label in labels[:count] if label.strip())[:160]
        for count in range(1, min(3, len(labels)) + 1)
    }
