"""Validate the complete WordNet/COW relation-candidate pilot artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.lexical_relation_candidate_validation import (
    LexicalRelationCandidateDataError,
    load_lexical_relation_candidate_records,
    validate_records,
)
from app.ai.lexical_source_validation import (
    LexicalSourceDataError,
    load_lexical_source_manifest,
    source_file_sha256,
    verify_lexical_source_file,
)
from app.db.seed import VocabularySeedRow, load_vocabulary_rows
from app.domain.lexical_source_readers import (
    parse_chinese_wordnet,
    parse_ecdict,
    parse_english_wordnet,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "lexical_source_manifest.json"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "build" / "lexical_sources"
DEFAULT_JSONL = PROJECT_ROOT / "data" / "word_lexical_relation_candidates.jsonl"
DEFAULT_PROVENANCE = (
    PROJECT_ROOT / "data" / "word_lexical_relation_candidates.provenance.json"
)


def validate(
    jsonl_path: Path = DEFAULT_JSONL,
    provenance_path: Path = DEFAULT_PROVENANCE,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    require_complete: bool = False,
) -> tuple[int, dict[str, int]]:
    manifest = load_lexical_source_manifest(manifest_path)
    contracts = {source.source_id: source for source in manifest.sources}
    required = {"ecdict", "oewn-2025", "omw-cmn-2"}
    if not required.issubset(contracts):
        raise LexicalSourceDataError("relation pilot source manifest is incomplete")
    paths = {
        source_id: source_dir / contracts[source_id].filename for source_id in required
    }
    for source_id, path in paths.items():
        verify_lexical_source_file(contracts[source_id], path)

    vocabulary = _load_vocabulary()
    with paths["ecdict"].open("r", encoding="utf-8", newline="") as source:
        ecdict, _ = parse_ecdict(source, None)
    target_words = {row.word for row in vocabulary}
    english = parse_english_wordnet(paths["oewn-2025"], target_words)
    chinese = parse_chinese_wordnet(paths["omw-cmn-2"])
    manifest_hash = source_file_sha256(manifest_path)
    records = load_lexical_relation_candidate_records(
        jsonl_path,
        sources=vocabulary,
        ecdict=ecdict,
        english=english,
        chinese_by_ili=chinese,
        manifest=manifest,
        manifest_sha256=manifest_hash,
        require_complete=require_complete,
    )
    report = validate_records(
        records,
        vocabulary,
        ecdict,
        english,
        chinese,
        manifest,
        manifest_sha256=manifest_hash,
        require_complete=require_complete,
    )
    if report.errors:
        raise LexicalRelationCandidateDataError("; ".join(report.errors[:20]))
    _validate_provenance(
        provenance_path,
        jsonl_path,
        manifest_path,
        manifest_hash,
        contracts,
        report.stats,
    )
    return 0, report.stats


def _validate_provenance(
    provenance_path: Path,
    jsonl_path: Path,
    manifest_path: Path,
    manifest_hash: str,
    contracts: dict,
    stats: dict[str, int],
) -> None:
    if not provenance_path.exists():
        raise LexicalRelationCandidateDataError(
            "relation-candidate provenance file is missing"
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
        if int(artifact["rows"]) != stats["total"]:
            raise ValueError("provenance row count does not match")
        if artifact["counts"] != stats:
            raise ValueError("provenance quality counts do not match")
        source_manifest = provenance["source_manifest"]
        if source_manifest["file"] != manifest_path.name:
            raise ValueError("provenance manifest filename does not match")
        if source_manifest["sha256"] != manifest_hash:
            raise ValueError("provenance manifest hash does not match")
        expected_ids = {"ecdict", "oewn-2025", "omw-cmn-2"}
        observed_ids = {item["source_id"] for item in provenance["sources"]}
        if observed_ids != expected_ids:
            raise ValueError("provenance source set does not match")
        for item in provenance["sources"]:
            contract = contracts[item["source_id"]]
            if item["version"] != contract.version:
                raise ValueError(
                    f"provenance version does not match: {item['source_id']}"
                )
            if item["file"] != contract.filename:
                raise ValueError(
                    f"provenance filename does not match: {item['source_id']}"
                )
            if item["sha256"] != contract.sha256:
                raise ValueError(f"provenance hash does not match: {item['source_id']}")
            if item["license"] != contract.license.identifier:
                raise ValueError(
                    f"provenance license does not match: {item['source_id']}"
                )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LexicalRelationCandidateDataError(
            f"invalid relation-candidate provenance: {exc}"
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
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        _, stats = validate(
            args.jsonl,
            args.provenance,
            manifest_path=args.manifest,
            source_dir=args.source_dir,
            require_complete=args.require_complete,
        )
    except (
        LexicalRelationCandidateDataError,
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
