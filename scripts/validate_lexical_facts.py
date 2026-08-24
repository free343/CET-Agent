"""Strict offline validator for the adaptive lexical-fact artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.lexical_fact_validation import (
    LexicalFactDataError,
    load_lexical_fact_records,
    validate_records,
)
from app.db.seed import load_vocabulary_rows

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSONL = PROJECT_ROOT / "data" / "word_lexical_facts.jsonl"
DEFAULT_PROVENANCE = PROJECT_ROOT / "data" / "word_lexical_facts.provenance.json"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(
    jsonl_path: Path = DEFAULT_JSONL,
    provenance_path: Path = DEFAULT_PROVENANCE,
    *,
    require_complete: bool = False,
) -> tuple[int, dict[str, int]]:
    source_paths = (
        PROJECT_ROOT / "data" / "sample_words.csv",
        PROJECT_ROOT / "data" / "cet_vocabulary_open.csv",
    )
    sources = [row for path in source_paths for row in load_vocabulary_rows(path)]
    records = load_lexical_fact_records(
        jsonl_path,
        sources=sources,
        require_complete=require_complete,
    )
    if not provenance_path.exists():
        raise LexicalFactDataError("lexical-fact provenance file is missing")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        artifact = provenance["artifact"]
        if artifact["file"] != jsonl_path.name:
            raise ValueError("provenance artifact filename does not match")
        if artifact["sha256"] != _digest(jsonl_path):
            raise ValueError("provenance artifact hash does not match")
        if int(artifact["rows"]) != len(records):
            raise ValueError("provenance row count does not match")
        source_metadata = {item["file"]: item for item in provenance["sources"]}
        for source_path in source_paths:
            if source_metadata.get(source_path.name, {}).get("sha256") != _digest(
                source_path
            ):
                raise ValueError(
                    f"provenance source hash does not match: {source_path.name}"
                )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LexicalFactDataError(f"invalid lexical-fact provenance: {exc}") from exc
    report = validate_records(records, sources, require_complete=require_complete)
    if report.errors:
        raise LexicalFactDataError("; ".join(report.errors[:20]))
    return 0, report.stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        _, stats = validate(
            args.jsonl,
            args.provenance,
            require_complete=args.require_complete,
        )
    except (LexicalFactDataError, FileNotFoundError) as exc:
        print(f"errors=1 {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"errors": 0, **stats}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
