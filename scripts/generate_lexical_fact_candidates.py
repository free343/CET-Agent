"""Generate candidate-only ECDICT form evidence for the bundled vocabulary.

The generated JSONL is a review queue, not a replacement for
``word_lexical_facts.jsonl``.  This command is offline and requires the
hash-verified source cache produced by ``audit_lexical_sources.py``.
"""

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
    validate_records,
)
from app.ai.lexical_fact_validation import load_lexical_fact_records
from app.ai.lexical_source_validation import (
    LexicalSourceDataError,
    load_lexical_source_manifest,
    source_file_sha256,
    verify_lexical_source_file,
)
from app.db.seed import VocabularySeedRow, load_vocabulary_rows
from app.domain.lexical_candidate_builder import build_candidate_record
from app.domain.lexical_source_readers import parse_ecdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "lexical_source_manifest.json"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "build" / "lexical_sources"
DEFAULT_FACTS = PROJECT_ROOT / "data" / "word_lexical_facts.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "word_lexical_fact_candidates.jsonl"
DEFAULT_PROVENANCE = (
    PROJECT_ROOT / "data" / "word_lexical_fact_candidates.provenance.json"
)


def generate(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    facts_path: Path = DEFAULT_FACTS,
    output_path: Path = DEFAULT_OUTPUT,
    provenance_path: Path = DEFAULT_PROVENANCE,
) -> dict[str, object]:
    manifest = load_lexical_source_manifest(manifest_path)
    ecdict_contract = next(
        (source for source in manifest.sources if source.source_id == "ecdict"), None
    )
    if ecdict_contract is None:  # pragma: no cover - manifest validator catches this
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
    fact_by_word = {fact.word: fact for fact in facts}
    records = [
        build_candidate_record(
            row,
            fact_by_word[row.word],
            ecdict.get(row.word),
            source_version=ecdict_contract.version,
            source_sha256=ecdict_contract.sha256,
            manifest_sha256=manifest_hash,
        )
        for row in vocabulary
    ]
    report = validate_records(
        records,
        vocabulary,
        facts,
        ecdict,
        manifest,
        manifest_sha256=manifest_hash,
        require_complete=True,
    )
    if report.errors:
        raise LexicalCandidateDataError("; ".join(report.errors[:20]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        for record in records:
            target.write(record.model_dump_json() + "\n")

    counts = {
        key: value
        for key, value in report.stats.items()
        if not key.startswith("roles_")
    }
    payload: dict[str, object] = {
        "schema_version": 1,
        "candidate_status": "candidate_only",
        "artifact": {
            "file": output_path.name,
            "sha256": _digest(output_path),
            "rows": len(records),
            "counts": counts,
        },
        "source_manifest": {
            "file": manifest_path.name,
            "sha256": manifest_hash,
        },
        "sources": [
            {
                "source_id": ecdict_contract.source_id,
                "version": ecdict_contract.version,
                "file": ecdict_path.name,
                "sha256": ecdict_contract.sha256,
                "license": ecdict_contract.license.identifier,
            }
        ],
        "transformation": (
            "ecdict-exchange-candidates-v1; exact headwords and documented exchange "
            "codes; conflicts are classified heuristically and remain candidate-only"
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
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    args = parser.parse_args()
    try:
        payload = generate(
            manifest_path=args.manifest,
            source_dir=args.source_dir,
            facts_path=args.facts,
            output_path=args.output,
            provenance_path=args.provenance,
        )
    except (
        LexicalCandidateDataError,
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
