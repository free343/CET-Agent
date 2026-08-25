from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HASH_PROTECTED_TEXT_FILES = (
    "data/cet_vocabulary_open.csv",
    "data/sample_words.csv",
    "data/lexical_source_manifest.json",
    "data/word_learning_aids.jsonl",
    "data/word_lexical_fact_candidates.jsonl",
    "data/word_lexical_facts.jsonl",
    "data/word_lexical_relation_candidates.jsonl",
)


def test_hash_protected_artifacts_have_a_stable_lf_checkout_policy() -> None:
    attributes_path = PROJECT_ROOT / ".gitattributes"

    assert attributes_path.exists(), "repository must define checkout line endings"
    rules = {
        line.strip()
        for line in attributes_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "* text=auto eol=lf" in rules

    for relative_path in HASH_PROTECTED_TEXT_FILES:
        content = (PROJECT_ROOT / relative_path).read_bytes()
        assert b"\r\n" not in content, f"{relative_path} must be committed as LF"
