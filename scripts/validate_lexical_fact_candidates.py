"""Validate the complete candidate-only ECDICT form evidence artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.lexical_candidate_validation import (
    LexicalCandidateDataError,
    load_lexical_candidate_records,
    validate_records,
)
from app.ai.lexical_fact_validation import load_lexical_fact_records
from app.ai.lexical_source_validation import (
    LexicalSourceDataError,
    load_lexical_source_manifest,
    source_file_sha256,
    verify_lexical_source_file,
)
from app.ai.schemas import LexicalSourceContract
from app.db.seed import VocabularySeedRow, load_vocabulary_rows
from app.domain.lexical_source_readers import parse_ecdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "lexical_source_manifest.json"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "build" / "lexical_sources"
DEFAULT_FACTS = PROJECT_ROOT / "data" / "word_lexical_facts.jsonl"
DEFAULT_JSONL = PROJECT_ROOT / "data" / "word_lexical_fact_candidates.jsonl"
DEFAULT_PROVENANCE = (
    PROJECT_ROOT / "data" / "word_lexical_fact_candidates.provenance.json"
)


def validate(
    jsonl_path: Path = DEFAULT_JSONL,
    provenance_path: Path = DEFAULT_PROVENANCE,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    facts_path: Path = DEFAULT_FACTS,
    require_complete: bool = False,
) -> tuple[int, dict[str, int]]:
    manifest = load_lexical_source_manifest(manifest_path)
    ecdict_contract = next(
        (source for source in manifest.sources if source.source_id == "ecdict"), None
    )
    if ecdict_contract is None:
        raise LexicalSourceDataError("lexical source manifest has no ECDICT contract")
    ecdict_path = source_dir / ecdict_contract.filename
    verify_lexical_source_file(ecdict_contract, ecdict_path)

    vocabulary = _load_vocabulary()
    facts = load_lexical_fact_records(
        facts_path,
        sources=vocabulary,
        require_complete=True,
    )
    target_words = {row.word for row in vocabulary}
    with ecdict_path.open("r", encoding="utf-8", newline="") as source:
        ecdict, _ = parse_ecdict(source, target_words)
    manifest_hash = source_file_sha256(manifest_path)
    records = load_lexical_candidate_records(
        jsonl_path,
        sources=vocabulary,
        facts=facts,
        ecdict=ecdict,
        manifest=manifest,
        manifest_sha256=manifest_hash,
        require_complete=require_complete,
    )
    report = validate_records(
        records,
        vocabulary,
        facts,
        ecdict,
        manifest,
        manifest_sha256=manifest_hash,
        require_complete=require_complete,
    )
    if report.errors:
        raise LexicalCandidateDataError("; ".join(report.errors[:20]))
    _validate_provenance(
        provenance_path,
        jsonl_path,
        manifest_path,
        manifest_hash,
        ecdict_contract,
        report.stats,
    )
    return 0, report.stats


def _validate_provenance(
    provenance_path: Path,
    jsonl_path: Path,
    manifest_path: Path,
    manifest_hash: str,
    ecdict_contract: LexicalSourceContract,
    stats: dict[str, int],
) -> None:
    if not provenance_path.exists():
        raise LexicalCandidateDataError("lexical-candidate provenance file is missing")
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
        if int(artifact["rows"]) != stats["total"]:
            raise ValueError("provenance row count does not match")
        expected_counts = {
            key: value for key, value in stats.items() if not key.startswith("roles_")
        }
        if artifact["counts"] != expected_counts:
            raise ValueError("provenance quality counts do not match")
        source_manifest = provenance["source_manifest"]
        if source_manifest["file"] != manifest_path.name:
            raise ValueError("provenance manifest filename does not match")
        if source_manifest["sha256"] != manifest_hash:
            raise ValueError("provenance manifest hash does not match")
        sources = provenance["sources"]
        if len(sources) != 1:
            raise ValueError("candidate provenance must contain one ECDICT source")
        source = sources[0]
        if source["source_id"] != ecdict_contract.source_id:
            raise ValueError("provenance source id does not match")
        if source["version"] != ecdict_contract.version:
            raise ValueError("provenance source version does not match")
        if source["file"] != ecdict_contract.filename:
            raise ValueError("provenance source filename does not match")
        if source["sha256"] != ecdict_contract.sha256:
            raise ValueError("provenance source hash does not match")
        if source["license"] != ecdict_contract.license.identifier:
            raise ValueError("provenance source license does not match")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LexicalCandidateDataError(
            f"invalid lexical-candidate provenance: {exc}"
        ) from exc


def _load_vocabulary() -> list[VocabularySeedRow]:
    rows: list[VocabularySeedRow] = []
    for name in ("sample_words.csv", "cet_vocabulary_open.csv"):
        rows.extend(load_vocabulary_rows(PROJECT_ROOT / "data" / name))
    if len(rows) != len({row.word for row in rows}):
        raise ValueError("bundled vocabulary contains duplicate headwords")
    return rows


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        _, stats = validate(
            args.jsonl,
            args.provenance,
            manifest_path=args.manifest,
            source_dir=args.source_dir,
            facts_path=args.facts,
            require_complete=args.require_complete,
        )
    except (
        LexicalCandidateDataError,
        LexicalSourceDataError,
        OSError,
        ValueError,
    ) as exc:
        print(f"errors=1 {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"errors": 0, **stats}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
