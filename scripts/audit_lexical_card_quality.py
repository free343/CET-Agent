"""Audit every learner-visible lexical relation, form, and source candidate.

The audit is intentionally offline and candidate-only.  It replays the pinned
ECDICT/WordNet/COW contracts, writes one JSON summary plus one JSONL detail row
for every checked relation/form, and never mutates the formal artifact or the
runtime database.  Domain-only translations are hard failures; morphology and
cross-source disagreements remain explicit human-review items instead of being
silently rewritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.lexical_candidate_validation import load_lexical_candidate_records
from app.ai.lexical_fact_validation import load_lexical_fact_records
from app.ai.lexical_relation_candidate_validation import (
    load_lexical_relation_candidate_records,
)
from app.ai.lexical_source_validation import (
    LexicalSourceDataError,
    load_lexical_source_manifest,
    source_file_sha256,
    verify_lexical_source_file,
)
from app.db.seed import VocabularySeedRow, load_vocabulary_rows
from app.domain.lexical_relation_quality import relation_translation_flags
from app.domain.lexical_source_readers import (
    parse_chinese_wordnet,
    parse_ecdict,
    parse_english_wordnet,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "lexical_source_manifest.json"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "build" / "lexical_sources"
DEFAULT_FACTS = PROJECT_ROOT / "data" / "word_lexical_facts.jsonl"
DEFAULT_FORM_CANDIDATES = PROJECT_ROOT / "data" / "word_lexical_fact_candidates.jsonl"
DEFAULT_RELATION_CANDIDATES = (
    PROJECT_ROOT / "data" / "word_lexical_relation_candidates.jsonl"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "build" / "lexical_card_quality_audit.json"
DEFAULT_DETAILS = PROJECT_ROOT / "build" / "lexical_card_quality_audit.jsonl"

_ROLE_TO_EXCHANGE = {
    "plural": "s",
    "past": "p",
    "past_participle": "d",
    "present_participle": "i",
    "third_person_singular": "3",
    "comparative": "r",
    "superlative": "t",
}


def _int_metric(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"audit metric {name} is not an integer")
    return value


def audit(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    facts_path: Path = DEFAULT_FACTS,
    form_candidates_path: Path = DEFAULT_FORM_CANDIDATES,
    relation_candidates_path: Path = DEFAULT_RELATION_CANDIDATES,
    output_path: Path = DEFAULT_OUTPUT,
    details_path: Path = DEFAULT_DETAILS,
) -> dict[str, object]:
    manifest = load_lexical_source_manifest(manifest_path)
    contracts = {source.source_id: source for source in manifest.sources}
    required = {"ecdict", "oewn-2025", "omw-cmn-2"}
    if not required.issubset(contracts):
        raise LexicalSourceDataError(
            "lexical quality audit source manifest is incomplete"
        )
    source_paths: dict[str, Path] = {}
    source_hashes: dict[str, str] = {}
    for source_id in sorted(required):
        contract = contracts[source_id]
        path = source_dir / contract.filename
        verify_lexical_source_file(contract, path)
        source_paths[source_id] = path
        source_hashes[source_id] = source_file_sha256(path)

    vocabulary = _load_vocabulary()
    source_by_word = {row.word: row for row in vocabulary}
    with source_paths["ecdict"].open("r", encoding="utf-8", newline="") as source:
        ecdict, _ = parse_ecdict(source, None)
    target_words = set(source_by_word)
    english = parse_english_wordnet(source_paths["oewn-2025"], target_words)
    chinese = parse_chinese_wordnet(source_paths["omw-cmn-2"])
    manifest_hash = source_file_sha256(manifest_path)

    facts = load_lexical_fact_records(
        facts_path,
        sources=vocabulary,
        require_complete=True,
    )
    form_candidates = load_lexical_candidate_records(
        form_candidates_path,
        sources=vocabulary,
        facts=facts,
        ecdict=ecdict,
        manifest=manifest,
        manifest_sha256=manifest_hash,
        require_complete=True,
    )
    relation_candidates = load_lexical_relation_candidate_records(
        relation_candidates_path,
        sources=vocabulary,
        ecdict=ecdict,
        english=english,
        chinese_by_ili=chinese,
        manifest=manifest,
        manifest_sha256=manifest_hash,
        require_complete=True,
    )

    details: list[dict[str, object]] = []
    form_summary = _audit_forms(
        vocabulary,
        facts,
        form_candidates,
        ecdict,
        details,
    )
    relation_summary = _audit_relations(
        relation_candidates,
        ecdict,
        details,
    )
    details.sort(
        key=lambda item: (
            str(item["kind"]),
            str(item["headword"]),
            str(item.get("role", "")),
            str(item.get("relation_type", "")),
            str(item.get("target", item.get("current", ""))),
        )
    )
    details_path.parent.mkdir(parents=True, exist_ok=True)
    with details_path.open("w", encoding="utf-8", newline="") as output:
        for item in details:
            output.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "offline-source-replay; candidate-only; no artifact or database mutation",
        "translation_review_method": {
            "principles": [
                "target-specific Chinese glosses",
                "part-of-speech filtering",
                "domain-only glosses are rejected",
                "cross-source disagreements remain explicit review items",
            ],
            "skill": "baoyu-translate",
        },
        "inputs": {
            "manifest": manifest_path.name,
            "manifest_sha256": manifest_hash,
            "source_sha256": dict(sorted(source_hashes.items())),
            "vocabulary_rows": len(vocabulary),
            "facts_rows": len(facts),
            "form_candidate_rows": len(form_candidates),
            "relation_candidate_rows": len(relation_candidates),
            "detail_file": details_path.name,
        },
        "forms": form_summary,
        "relations": relation_summary,
        "gate": {
            "hard_failures": _int_metric(
                relation_summary["domain_only_translation"],
                "domain_only_translation",
            ),
            "human_review_items": _int_metric(
                form_summary["formal_conflicts"], "formal_conflicts"
            )
            + _int_metric(
                form_summary["candidate_source_conflicts"],
                "candidate_source_conflicts",
            )
            + _int_metric(
                relation_summary["synonym_sense_translation_mismatch"],
                "synonym_sense_translation_mismatch",
            ),
            "learner_visible_domain_only_relations": 0,
            "policy": (
                "Do not promote relation/form candidates automatically. Hide domain-only "
                "relation translations and keep unresolved morphology or sense conflicts "
                "in the review ledger."
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _audit_forms(
    vocabulary: list[VocabularySeedRow],
    facts: list,
    candidates: list,
    ecdict: dict,
    details: list[dict[str, object]],
) -> dict[str, object]:
    fact_by_word = {record.word: record for record in facts}
    candidate_by_word = {record.word: record for record in candidates}
    formal_status: Counter[str] = Counter()
    formal_by_role: Counter[str] = Counter()
    candidate_status: Counter[str] = Counter()
    candidate_by_role: Counter[str] = Counter()
    for row in vocabulary:
        fact = fact_by_word[row.word]
        entry = ecdict.get(row.word)
        for paradigm in fact.forms:
            for form in paradigm.forms:
                role = form.role
                code = _ROLE_TO_EXCHANGE.get(role)
                source_values = (
                    list(entry.exchange.get(code, ())) if entry and code else []
                )
                current_values = _split_values(form.value)
                status = _form_status(current_values, source_values)
                formal_status[status] += 1
                formal_by_role[role] += 1
                details.append(
                    {
                        "kind": "formal_form",
                        "headword": row.word,
                        "role": role,
                        "current": current_values,
                        "source": source_values,
                        "status": status,
                    }
                )
        candidate = candidate_by_word[row.word]
        for item in candidate.candidates:
            candidate_status[item.outcome] += 1
            candidate_by_role[item.role] += 1
            details.append(
                {
                    "kind": "form_candidate",
                    "headword": row.word,
                    "role": item.role,
                    "current": item.current_forms,
                    "source": item.source_forms,
                    "status": item.outcome,
                    "conflict_kind": item.conflict_kind,
                }
            )
    return {
        "formal_forms_checked": sum(formal_status.values()),
        "formal_conflicts": formal_status["conflict"],
        "formal_missing_source": formal_status["missing_source"],
        "formal_source_agreements": formal_status["corroborated"],
        "formal_by_role": dict(sorted(formal_by_role.items())),
        "formal_status": dict(sorted(formal_status.items())),
        "candidate_forms_checked": sum(candidate_status.values()),
        "candidate_source_conflicts": candidate_status["source_conflict"],
        "candidate_source_additions": candidate_status["source_addition"],
        "candidate_source_agreements": candidate_status["source_agrees"],
        "candidate_by_role": dict(sorted(candidate_by_role.items())),
        "candidate_status": dict(sorted(candidate_status.items())),
    }


def _audit_relations(
    records: list,
    ecdict: dict,
    details: list[dict[str, object]],
) -> dict[str, object]:
    status: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    item_counts: Counter[str] = Counter()
    words_by_status: dict[str, set[str]] = {}
    items = 0
    for record in records:
        for group in record.groups:
            group_counts[group.relation_type] += 1
            for item in group.items:
                items += 1
                entry = ecdict[item.word]
                flags = relation_translation_flags(
                    group.sense,
                    entry,
                    relation_type=group.relation_type,
                )
                if not flags:
                    status["checked_ok"] += 1
                for flag in flags:
                    status[flag] += 1
                    words_by_status.setdefault(flag, set()).add(record.word)
                item_counts[group.relation_type] += 1
                details.append(
                    {
                        "kind": "relation",
                        "headword": record.word,
                        "relation_type": group.relation_type,
                        "part_of_speech": group.part_of_speech,
                        "source_sense": group.sense,
                        "target": item.word,
                        "translation": item.meaning,
                        "flags": list(flags),
                    }
                )
    return {
        "groups_checked": sum(group_counts.values()),
        "items_checked": items,
        "synonym_groups": group_counts["synonym"],
        "antonym_groups": group_counts["antonym"],
        "synonym_items": item_counts["synonym"],
        "antonym_items": item_counts["antonym"],
        "checked_ok": status["checked_ok"],
        "domain_only_translation": status["domain_only_translation"],
        "missing_translation": status["missing_translation"],
        "synonym_sense_translation_mismatch": status["sense_translation_mismatch"],
        "words_with_domain_only_translation": len(
            words_by_status.get("domain_only_translation", set())
        ),
        "words_with_sense_translation_mismatch": len(
            words_by_status.get("sense_translation_mismatch", set())
        ),
    }


def _form_status(current: list[str], source: list[str]) -> str:
    if not source:
        return "missing_source"
    if set(current).intersection(source):
        return "corroborated"
    return "conflict"


def _split_values(value: str) -> list[str]:
    return [item.strip().casefold() for item in value.split("/") if item.strip()]


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
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--form-candidates", type=Path, default=DEFAULT_FORM_CANDIDATES)
    parser.add_argument(
        "--relation-candidates", type=Path, default=DEFAULT_RELATION_CANDIDATES
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    args = parser.parse_args()
    try:
        report = audit(
            manifest_path=args.manifest,
            source_dir=args.source_dir,
            facts_path=args.facts,
            form_candidates_path=args.form_candidates,
            relation_candidates_path=args.relation_candidates,
            output_path=args.output,
            details_path=args.details,
        )
    except (LexicalSourceDataError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    gate = report["gate"]
    if not isinstance(gate, dict):
        print("ERROR: audit report gate is not an object", file=sys.stderr)
        return 1
    print(json.dumps({"errors": 0, **gate}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
