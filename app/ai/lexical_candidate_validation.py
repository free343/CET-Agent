"""Strict validation for the candidate-only lexical form evidence artifact."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.ai.schemas import (
    LexicalFactCandidateRecord,
    LexicalFactRecord,
    LexicalFormCandidate,
    LexicalSourceManifest,
)
from app.db.seed import VocabularySeedRow
from app.domain.lexical_candidate_builder import (
    FORM_CANDIDATE_SOURCE,
    ROLE_TO_EXCHANGE,
)
from app.domain.lexical_source_readers import ECDICTEntry


class LexicalCandidateDataError(ValueError):
    """Raised when candidate evidence is malformed or inconsistent."""


@dataclass(slots=True)
class LexicalCandidateValidationReport:
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _canonical_payload(record: LexicalFactCandidateRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "word": record.word,
        "level": record.level,
        "source_kind": record.source_kind,
        "source_meaning": record.source_meaning,
        "candidates": [
            candidate.model_dump(mode="json") for candidate in record.candidates
        ],
        "candidate_status": record.candidate_status,
        "source_manifest_sha256": record.source_manifest_sha256,
        "source": record.source,
    }


def lexical_candidate_content_hash(record: LexicalFactCandidateRecord) -> str:
    canonical = json.dumps(
        _canonical_payload(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_record(
    record: LexicalFactCandidateRecord,
    source: VocabularySeedRow | None,
    fact: LexicalFactRecord | None,
    entry: ECDICTEntry | None,
    manifest: LexicalSourceManifest,
    *,
    manifest_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if source is None:
        return [f"{record.word}: unknown word not present in vocabulary sources"]
    if fact is None:
        errors.append(f"{record.word}: corresponding lexical-fact record is missing")
    if record.level != source.level.value:
        errors.append(f"{record.word}: level differs from vocabulary source")
    expected_kind = "curated" if source.example else "open"
    if record.source_kind != expected_kind:
        errors.append(f"{record.word}: source_kind differs from vocabulary source")
    if record.source_meaning.strip() != source.meaning.strip():
        errors.append(f"{record.word}: source_meaning differs from vocabulary source")
    if record.candidate_status != "candidate_only":
        errors.append(f"{record.word}: candidate_status must remain candidate_only")
    if record.source != FORM_CANDIDATE_SOURCE:
        errors.append(f"{record.word}: unexpected candidate source identifier")
    if record.source_manifest_sha256 != manifest_sha256:
        errors.append(f"{record.word}: source manifest hash does not match")
    if record.content_hash != lexical_candidate_content_hash(record):
        errors.append(f"{record.word}: content_hash does not match canonical content")

    ecdict_contract = next(
        (item for item in manifest.sources if item.source_id == "ecdict"), None
    )
    if ecdict_contract is None:
        errors.append("manifest: ecdict contract is missing")
    expected_current = _fact_forms_by_role(fact) if fact is not None else {}
    expected_candidates = {
        role: _flatten_forms(entry.exchange.get(code, ()))
        for role, code in ROLE_TO_EXCHANGE.items()
        if entry is not None and entry.exchange.get(code)
    }
    seen_roles: set[str] = set()
    for candidate in record.candidates:
        if candidate.role in seen_roles:
            errors.append(f"{record.word}: duplicate candidate role {candidate.role}")
        seen_roles.add(candidate.role)
        expected_source = expected_candidates.get(candidate.role, [])
        expected_role_current = expected_current.get(candidate.role, [])
        if candidate.current_forms != expected_role_current:
            errors.append(f"{record.word}:{candidate.role}: current forms differ")
        if candidate.source_forms != expected_source:
            errors.append(f"{record.word}:{candidate.role}: source forms differ")
        if not expected_source:
            errors.append(f"{record.word}:{candidate.role}: source code is unavailable")
        if len(candidate.evidence) != 1:
            errors.append(
                f"{record.word}:{candidate.role}: exactly one evidence pointer is required"
            )
        elif ecdict_contract is not None:
            evidence = candidate.evidence[0]
            expected_locator = (
                f"ecdict.csv:word={record.word}:code={ROLE_TO_EXCHANGE[candidate.role]}"
            )
            if evidence.source_id != "ecdict":
                errors.append(
                    f"{record.word}:{candidate.role}: evidence source is not ECDICT"
                )
            if evidence.source_version != ecdict_contract.version:
                errors.append(
                    f"{record.word}:{candidate.role}: evidence version differs"
                )
            if evidence.field != "exchange":
                errors.append(
                    f"{record.word}:{candidate.role}: evidence field is not exchange"
                )
            if evidence.locator != expected_locator:
                errors.append(
                    f"{record.word}:{candidate.role}: evidence locator differs"
                )
            if evidence.source_sha256 != ecdict_contract.sha256:
                errors.append(f"{record.word}:{candidate.role}: evidence hash differs")
        _validate_outcome(record.word, candidate, errors)

    for role in expected_candidates:
        if role not in seen_roles:
            errors.append(f"{record.word}: missing candidate role {role}")
    return errors


def validate_records(
    records: Sequence[LexicalFactCandidateRecord],
    sources: Sequence[VocabularySeedRow],
    facts: Sequence[LexicalFactRecord],
    ecdict: dict[str, ECDICTEntry],
    manifest: LexicalSourceManifest,
    *,
    manifest_sha256: str,
    require_complete: bool = False,
) -> LexicalCandidateValidationReport:
    report = LexicalCandidateValidationReport()
    source_by_word = {row.word: row for row in sources}
    fact_by_word = {record.word: record for record in facts}
    seen: set[str] = set()
    for record in records:
        if record.word in seen:
            report.errors.append(f"duplicate lexical candidate record: {record.word}")
        seen.add(record.word)
        report.errors.extend(
            validate_record(
                record,
                source_by_word.get(record.word),
                fact_by_word.get(record.word),
                ecdict.get(record.word),
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
                f"missing lexical candidate records: {', '.join(missing[:12])}"
            )
        if extra:
            report.errors.append(
                f"unknown lexical candidate records: {', '.join(extra[:12])}"
            )
        if len(records) != len(expected):
            report.errors.append(
                f"record count {len(records)} does not equal source count {len(expected)}"
            )

    outcome_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    for record in records:
        for candidate in record.candidates:
            outcome_counts[candidate.outcome] += 1
            kind_counts[candidate.conflict_kind] += 1
            role_counts[candidate.role] += 1
    report.stats = {
        "total": len(records),
        "records_with_candidates": sum(bool(record.candidates) for record in records),
        "candidate_entries": sum(len(record.candidates) for record in records),
        "source_additions": outcome_counts["source_addition"],
        "source_agreements": outcome_counts["source_agrees"],
        "source_conflicts": outcome_counts["source_conflict"],
        **{
            f"candidate_kind_{key}": value for key, value in sorted(kind_counts.items())
        },
        **{f"roles_{key}": value for key, value in sorted(role_counts.items())},
    }
    return report


def load_lexical_candidate_records(
    jsonl_path: Path,
    *,
    sources: Sequence[VocabularySeedRow] | None = None,
    facts: Sequence[LexicalFactRecord] | None = None,
    ecdict: dict[str, ECDICTEntry] | None = None,
    manifest: LexicalSourceManifest | None = None,
    manifest_sha256: str | None = None,
    require_complete: bool = False,
) -> list[LexicalFactCandidateRecord]:
    """Read and optionally validate the entire candidate artifact."""

    if not jsonl_path.exists():
        return []
    raw_records: list[LexicalFactCandidateRecord] = []
    with jsonl_path.open("r", encoding="utf-8", newline="") as source:
        for line_number, raw in enumerate(source, start=1):
            if not raw.strip():
                raise LexicalCandidateDataError(
                    f"{jsonl_path.name}:{line_number} is empty"
                )
            try:
                raw_records.append(
                    LexicalFactCandidateRecord.model_validate(json.loads(raw))
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                raise LexicalCandidateDataError(
                    f"{jsonl_path.name}:{line_number} violates the lexical-candidate contract"
                ) from exc
    context = (sources, facts, ecdict, manifest, manifest_sha256)
    if all(value is None for value in context):
        return raw_records
    if any(value is None for value in context):
        raise LexicalCandidateDataError(
            "candidate validation requires all source, fact, ECDICT, and manifest inputs"
        )
    assert sources is not None
    assert facts is not None
    assert ecdict is not None
    assert manifest is not None
    assert manifest_sha256 is not None
    report = validate_records(
        raw_records,
        sources,
        facts,
        ecdict,
        manifest,
        manifest_sha256=manifest_sha256,
        require_complete=require_complete,
    )
    if report.errors:
        raise LexicalCandidateDataError(
            f"{jsonl_path.name} failed validation: {'; '.join(report.errors[:20])}"
        )
    return raw_records


def _validate_outcome(
    word: str, candidate: LexicalFormCandidate, errors: list[str]
) -> None:
    current = set(candidate.current_forms)
    source = set(candidate.source_forms)
    outcome = candidate.outcome
    kind = candidate.conflict_kind
    if outcome == "source_addition":
        if current or not source or kind != "missing_current_form":
            errors.append(
                f"{word}:{candidate.role}: invalid source_addition classification"
            )
    elif outcome == "source_agrees":
        if (
            not current
            or not source
            or not current.intersection(source)
            or kind != "corroborated"
        ):
            errors.append(
                f"{word}:{candidate.role}: invalid source_agrees classification"
            )
    elif outcome == "source_conflict" and (
        not current
        or not source
        or current.intersection(source)
        or kind in {"missing_current_form", "corroborated"}
    ):
        errors.append(
            f"{word}:{candidate.role}: invalid source_conflict classification"
        )


def _fact_forms_by_role(fact: LexicalFactRecord | None) -> dict[str, list[str]]:
    if fact is None:
        return {}
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


def _flatten_forms(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for raw in values:
        for value in raw.split("/"):
            normalized = value.strip().casefold()
            if normalized and normalized not in result:
                result.append(normalized)
    return result
