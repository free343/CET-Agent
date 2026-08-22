"""Deterministic tests for the offline word learning-aid validator."""

from __future__ import annotations

import json

import pytest

from scripts.validate_word_learning_aids import (
    SourceEntry,
    read_records,
    validate_record,
    validate_records,
)


def _entry(
    word, *, level="CET4", meaning="释义", example="", kind="open"
) -> SourceEntry:
    return SourceEntry(
        word=word, level=level, meaning=meaning, example=example, source_kind=kind
    )


def _record(
    word,
    *,
    level="CET4",
    meaning="释义",
    example=None,
    origin=None,
    kind="open",
    collocations=None,
    word_family=None,
    model="deepseek-chat",
) -> dict:
    curated = kind == "curated"
    example = (
        example
        if example is not None
        else (f"Curated {word} example." if curated else f"Students learn {word} here.")
    )
    origin = (
        origin if origin is not None else ("curated" if curated else "ai_generated")
    )
    return {
        "schema_version": 1,
        "word": word,
        "level": level,
        "source_kind": kind,
        "source_meaning": meaning,
        "example": example,
        "example_translation": f"{word} 的翻译。",
        "example_origin": origin,
        "collocations": collocations
        if collocations is not None
        else [
            {"phrase": f"{word} phrase", "meaning": "搭配一"},
            {"phrase": f"common {word}", "meaning": "搭配二"},
        ],
        "word_family": word_family if word_family is not None else [],
        "generator": {
            "provider": "deepseek",
            "model": model,
            "prompt_version": "word-learning-aids-v1",
        },
        "content_status": "ai_generated_unreviewed",
    }


def _validate(word="alpha", by_word=None, **kwargs) -> list[str]:
    if by_word is None:
        by_word = {
            "alpha": _entry(
                "alpha",
                example="Curated alpha example."
                if kwargs.get("kind") == "curated"
                else "",
            )
        }
    from app.ai.schemas import WordLearningAidRecord

    model = WordLearningAidRecord.model_validate(_record(word, **kwargs))
    return validate_record(model, by_word)


def test_valid_open_record_passes() -> None:
    by_word = {"alpha": _entry("alpha")}
    assert _validate("alpha", by_word=by_word) == []


def test_unknown_word_is_rejected() -> None:
    assert _validate("alpha", by_word={}) == [
        "alpha: unknown word not present in the source CSVs"
    ]


def test_level_mismatch_is_rejected() -> None:
    by_word = {"alpha": _entry("alpha", level="CET6")}
    assert _validate("alpha", by_word=by_word, level="CET4")


def test_curated_example_must_match_csv() -> None:
    by_word = {
        "alpha": _entry("alpha", example="Exact curated example.", kind="curated")
    }
    errors = _validate(
        "alpha",
        by_word=by_word,
        kind="curated",
        example="Different example.",
        origin="curated",
    )
    assert any("curated example differs" in e for e in errors)


def test_open_example_origin_must_be_generated() -> None:
    by_word = {"alpha": _entry("alpha")}
    errors = _validate("alpha", by_word=by_word, origin="curated")
    assert any("ai_generated" in e for e in errors)


def test_example_must_contain_standalone_word() -> None:
    by_word = {"alpha": _entry("alpha")}
    errors = _validate("alpha", by_word=by_word, example="Students learn alphas here.")
    assert any("standalone headword" in e for e in errors)


def test_example_must_end_with_terminal_punctuation() -> None:
    by_word = {"alpha": _entry("alpha")}
    errors = _validate("alpha", by_word=by_word, example="Students learn alpha here")
    assert any("must end with" in e for e in errors)


def test_duplicate_collocations_are_rejected() -> None:
    by_word = {"alpha": _entry("alpha")}
    collocations = [
        {"phrase": "alpha phrase", "meaning": "搭配一"},
        {"phrase": "  Alpha   phrase ", "meaning": "搭配二"},
    ]
    errors = _validate("alpha", by_word=by_word, collocations=collocations)
    assert any("duplicate collocation" in e for e in errors)


def test_word_family_cannot_contain_self() -> None:
    by_word = {"alpha": _entry("alpha")}
    family = [
        {"word": "alpha", "part_of_speech": "n.", "meaning": "自己", "relation": "base"}
    ]
    errors = _validate("alpha", by_word=by_word, word_family=family)
    assert any("target word itself" in e for e in errors)


def test_word_family_inflection_is_rejected() -> None:
    by_word = {"alpha": _entry("alpha")}
    family = [
        {
            "word": "alphas",
            "part_of_speech": "n.",
            "meaning": "复数",
            "relation": "base",
        }
    ]
    errors = _validate("alpha", by_word=by_word, word_family=family)
    assert any("inflection" in e for e in errors)


def test_word_family_real_derivative_passes() -> None:
    by_word = {"adapt": _entry("adapt")}
    family = [
        {
            "word": "adaptable",
            "part_of_speech": "adj.",
            "meaning": "适应性强的",
            "relation": "derivative",
        }
    ]
    errors = _validate("adapt", by_word=by_word, word_family=family)
    assert errors == []


def test_generator_model_unknown_is_rejected() -> None:
    by_word = {"alpha": _entry("alpha")}
    errors = _validate("alpha", by_word=by_word, model="unknown")
    assert any("must not be 'unknown'" in e for e in errors)


def test_require_complete_rejects_word_set_mismatch() -> None:
    ordered = [_entry("alpha"), _entry("beta")]
    by_word = {e.word: e for e in ordered}
    records = [_record("alpha")]
    report = validate_records(records, ordered, by_word, require_complete=True)
    assert any("word set mismatch" in e for e in report.errors)


def test_require_complete_rejects_wrong_order() -> None:
    ordered = [_entry("alpha"), _entry("beta")]
    by_word = {e.word: e for e in ordered}
    records = [_record("beta"), _record("alpha")]
    report = validate_records(records, ordered, by_word, require_complete=True)
    assert any("word order" in e for e in report.errors)


def test_require_complete_passes_exact_set_in_order() -> None:
    ordered = [_entry("alpha"), _entry("beta")]
    by_word = {e.word: e for e in ordered}
    records = [_record("alpha"), _record("beta")]
    report = validate_records(records, ordered, by_word, require_complete=True)
    assert report.errors == []
    assert report.stats["total"] == 2


def test_duplicate_words_in_jsonl_are_rejected() -> None:
    ordered = [_entry("alpha")]
    by_word = {e.word: e for e in ordered}
    records = [_record("alpha"), _record("alpha")]
    report = validate_records(records, ordered, by_word, require_complete=False)
    assert any("duplicate words" in e for e in report.errors)


def test_read_records_rejects_malformed_lines(tmp_path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_records(bad)

    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_records(empty)


def test_read_records_parses_compact_lines(tmp_path) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text(json.dumps(_record("alpha")) + "\n", encoding="utf-8")
    records = read_records(good)
    assert records == [_record("alpha")]
