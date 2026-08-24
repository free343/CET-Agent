"""Generate the source-backed WordNet/COW relation-candidate overlay."""

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
    validate_records,
)
from app.ai.lexical_source_validation import (
    LexicalSourceDataError,
    load_lexical_source_manifest,
    source_file_sha256,
    verify_lexical_source_file,
)
from app.db.seed import VocabularySeedRow, load_vocabulary_rows
from app.domain.lexical_relation_candidate_builder import (
    build_relation_candidate_record,
)
from app.domain.lexical_source_readers import (
    parse_chinese_wordnet,
    parse_ecdict,
    parse_english_wordnet,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "lexical_source_manifest.json"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "build" / "lexical_sources"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "word_lexical_relation_candidates.jsonl"
DEFAULT_PROVENANCE = (
    PROJECT_ROOT / "data" / "word_lexical_relation_candidates.provenance.json"
)


def generate(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_path: Path = DEFAULT_OUTPUT,
    provenance_path: Path = DEFAULT_PROVENANCE,
) -> dict[str, object]:
    manifest = load_lexical_source_manifest(manifest_path)
    contracts = {source.source_id: source for source in manifest.sources}
    required = {"ecdict", "oewn-2025", "omw-cmn-2"}
    if not required.issubset(contracts):
        raise LexicalSourceDataError("relation pilot source manifest is incomplete")
    source_paths: dict[str, Path] = {}
    source_hashes: dict[str, str] = {}
    for source_id in sorted(required):
        contract = contracts[source_id]
        path = source_dir / contract.filename
        verify_lexical_source_file(contract, path)
        source_paths[source_id] = path
        source_hashes[source_id] = source_file_sha256(path)

    vocabulary = _load_vocabulary()
    with source_paths["ecdict"].open("r", encoding="utf-8", newline="") as source:
        # Keep the full ECDICT index so a relation target may be displayed as
        # a reference even when it is outside the CET learning bank.  Such a
        # target never creates a Word or a scheduling obligation.
        ecdict, _ = parse_ecdict(source, None)
    target_words = {row.word for row in vocabulary}
    english = parse_english_wordnet(source_paths["oewn-2025"], target_words)
    chinese = parse_chinese_wordnet(source_paths["omw-cmn-2"])
    manifest_hash = source_file_sha256(manifest_path)
    records = [
        build_relation_candidate_record(
            row,
            english,
            chinese,
            ecdict,
            oewn_version=contracts["oewn-2025"].version,
            oewn_sha256=contracts["oewn-2025"].sha256,
            cow_version=contracts["omw-cmn-2"].version,
            cow_sha256=contracts["omw-cmn-2"].sha256,
            ecdict_version=contracts["ecdict"].version,
            ecdict_sha256=contracts["ecdict"].sha256,
            manifest_sha256=manifest_hash,
        )
        for row in vocabulary
    ]
    report = validate_records(
        records,
        vocabulary,
        ecdict,
        english,
        chinese,
        manifest,
        manifest_sha256=manifest_hash,
        require_complete=True,
    )
    if report.errors:
        raise LexicalRelationCandidateDataError("; ".join(report.errors[:20]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        for record in records:
            target.write(record.model_dump_json() + "\n")

    payload: dict[str, object] = {
        "schema_version": 1,
        "candidate_status": "candidate_only",
        "artifact": {
            "file": output_path.name,
            "sha256": _digest(output_path),
            "rows": len(records),
            "counts": report.stats,
        },
        "source_manifest": {
            "file": manifest_path.name,
            "sha256": manifest_hash,
        },
        "sources": [
            {
                "source_id": source_id,
                "version": contracts[source_id].version,
                "file": source_paths[source_id].name,
                "sha256": source_hashes[source_id],
                "license": contracts[source_id].license.identifier,
            }
            for source_id in sorted(required)
        ],
        "transformation": (
            "wordnet-cow-relation-candidates-v3; Chinese-overlap-aligned WordNet "
            "senses, single-word ECDICT targets (including outside-bank reference "
            "words), ordinary-language ECDICT translation required, ECDICT "
            "frequency greater than zero, at most six targets per relation type, "
            "and at most four groups per headword"
        ),
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


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
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    args = parser.parse_args()
    try:
        payload = generate(
            manifest_path=args.manifest,
            source_dir=args.source_dir,
            output_path=args.output,
            provenance_path=args.provenance,
        )
    except (
        LexicalRelationCandidateDataError,
        LexicalSourceDataError,
        OSError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload["artifact"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
