"""Audit pinned dictionary sources before promoting lexical-card facts.

The command is deliberately candidate-only: it verifies source rights and
integrity, measures form/relation coverage, and writes a deterministic report.
It never mutates the formal lexical-fact artifact or the runtime database.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.lexical_fact_validation import load_lexical_fact_records
from app.ai.lexical_source_validation import (
    LexicalSourceDataError,
    load_lexical_source_manifest,
    source_file_sha256,
    verify_lexical_source_file,
)
from app.ai.schemas import LexicalSourceContract
from app.db.seed import VocabularySeedRow, load_vocabulary_rows
from app.domain.lexical_source_audit import build_audit_report
from app.domain.lexical_source_readers import (
    parse_chinese_wordnet,
    parse_ecdict,
    parse_english_wordnet,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "lexical_source_manifest.json"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "build" / "lexical_sources"
DEFAULT_OUTPUT = PROJECT_ROOT / "build" / "lexical_sources" / "audit.json"
DEFAULT_FACTS = PROJECT_ROOT / "data" / "word_lexical_facts.jsonl"


def run_audit(
    manifest_path: Path,
    source_dir: Path,
    output_path: Path,
    *,
    download_missing: bool = False,
) -> dict[str, object]:
    manifest = load_lexical_source_manifest(manifest_path)
    source_dir.mkdir(parents=True, exist_ok=True)
    if download_missing:
        _download_missing_sources(manifest.sources, source_dir)
    source_paths: dict[str, Path] = {}
    source_hashes: dict[str, str] = {}
    for contract in manifest.sources:
        path = source_dir / contract.filename
        verify_lexical_source_file(contract, path)
        source_paths[contract.source_id] = path
        source_hashes[contract.source_id] = source_file_sha256(path)

    vocabulary = _load_vocabulary()
    target_words = {row.word for row in vocabulary}
    facts = load_lexical_fact_records(DEFAULT_FACTS)
    with source_paths["ecdict"].open("r", encoding="utf-8", newline="") as source:
        ecdict, exchange_codes = parse_ecdict(source, target_words)
    english = parse_english_wordnet(source_paths["oewn-2025"], target_words)
    chinese = parse_chinese_wordnet(source_paths["omw-cmn-2"])
    report = build_audit_report(
        vocabulary,
        facts,
        ecdict,
        exchange_codes,
        english,
        chinese,
        source_hashes,
        manifest_hash=source_file_sha256(manifest_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _download_missing_sources(
    sources: list[LexicalSourceContract], source_dir: Path
) -> None:
    for contract in sources:
        destination = source_dir / contract.filename
        if destination.exists():
            verify_lexical_source_file(contract, destination)
            continue
        partial = destination.with_name(destination.name + ".part")
        try:
            with httpx.stream(
                "GET",
                contract.url,
                follow_redirects=True,
                timeout=httpx.Timeout(240.0, connect=30.0),
            ) as response:
                response.raise_for_status()
                with partial.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
            verify_lexical_source_file(contract, partial)
            partial.replace(destination)
        except Exception:
            partial.unlink(missing_ok=True)
            raise


def _load_vocabulary() -> list[VocabularySeedRow]:
    rows: list[VocabularySeedRow] = []
    for name in ("sample_words.csv", "cet_vocabulary_open.csv"):
        rows.extend(load_vocabulary_rows(PROJECT_ROOT / "data" / name))
    if len(rows) != len({row.word for row in rows}):
        raise ValueError("bundled vocabulary contains duplicate headwords")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--download-missing", action="store_true")
    args = parser.parse_args()
    try:
        report = run_audit(
            args.manifest,
            args.source_dir,
            args.output,
            download_missing=args.download_missing,
        )
    except (LexicalSourceDataError, OSError, ValueError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
