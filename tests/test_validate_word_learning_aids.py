"""Deterministic tests for the offline word learning-aid validator."""

from __future__ import annotations

import json
from hashlib import sha256

import pytest

from scripts.validate_word_learning_aids import (
    SourceEntry,
    ValidationReport,
    read_records,
    validate_provenance,
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
        else (
            f"Curated {word} example."
            if curated
            else f"Students carefully learn {word} in class today."
        )
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


def test_example_must_contain_target_word_or_regular_form() -> None:
    by_word = {"alpha": _entry("alpha")}
    errors = _validate("alpha", by_word=by_word, example="Students learn here.")
    assert any("standalone headword" in e for e in errors)


def test_open_example_may_use_a_regular_word_form() -> None:
    by_word = {"alpha": _entry("alpha")}
    assert (
        _validate(
            "alpha",
            by_word=by_word,
            example="Students learn alphas during the first class today.",
        )
        == []
    )


def test_curated_example_may_use_a_regular_word_form_when_preserved() -> None:
    by_word = {
        "complement": _entry(
            "complement",
            kind="curated",
            example="The sauce complements the fresh vegetables.",
        )
    }
    assert (
        _validate(
            "complement",
            by_word=by_word,
            kind="curated",
            example="The sauce complements the fresh vegetables.",
            origin="curated",
        )
        == []
    )


def test_example_must_end_with_terminal_punctuation() -> None:
    by_word = {"alpha": _entry("alpha")}
    errors = _validate("alpha", by_word=by_word, example="Students learn alpha here")
    assert any("must end with" in e for e in errors)


def test_generated_example_must_contain_six_to_eighteen_words() -> None:
    by_word = {"alpha": _entry("alpha")}
    errors = _validate("alpha", by_word=by_word, example="I saw alpha.")
    assert any("6 to 18 English words" in e for e in errors)


def test_duplicate_collocations_are_rejected() -> None:
    by_word = {"alpha": _entry("alpha")}
    collocations = [
        {"phrase": "alpha phrase", "meaning": "搭配一"},
        {"phrase": "  Alpha   phrase ", "meaning": "搭配二"},
    ]
    errors = _validate("alpha", by_word=by_word, collocations=collocations)
    assert any("duplicate collocation" in e for e in errors)


def test_collocation_must_contain_target_word_or_regular_inflection() -> None:
    by_word = {"study": _entry("study")}
    valid = [
        {"phrase": "study plan", "meaning": "学习计划"},
        {"phrase": "studying abroad", "meaning": "出国留学"},
    ]
    assert _validate("study", by_word=by_word, collocations=valid) == []

    invalid = [
        {"phrase": "read books", "meaning": "读书"},
        {"phrase": "learn quickly", "meaning": "快速学习"},
    ]
    errors = _validate("study", by_word=by_word, collocations=invalid)
    assert sum("must contain the target word" in error for error in errors) == 2


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


def test_lexicalized_ed_form_can_be_a_word_family_derivative() -> None:
    by_word = {"principle": _entry("principle")}
    family = [
        {
            "word": "principled",
            "part_of_speech": "adj.",
            "meaning": "有原则的",
            "relation": "derivative",
        }
    ]
    assert _validate("principle", by_word=by_word, word_family=family) == []


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


def test_provenance_rejects_artifact_source_and_stats_mismatch(tmp_path) -> None:
    artifact = tmp_path / "word_learning_aids.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")
    curated = tmp_path / "sample_words.csv"
    curated.write_text("curated", encoding="utf-8")
    open_csv = tmp_path / "cet_vocabulary_open.csv"
    open_csv.write_text("open", encoding="utf-8")
    report = ValidationReport(
        errors=[],
        stats={"total": 1},
        generator_models={"deepseek-v4-flash"},
    )
    provenance = tmp_path / "word_learning_aids.provenance.json"
    payload = {
        "generator": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "prompt_version": "word-learning-aids-v1",
        },
        "source_files": {
            curated.name: sha256(curated.read_bytes()).hexdigest(),
            open_csv.name: sha256(open_csv.read_bytes()).hexdigest(),
        },
        "artifact": {
            "path": artifact.name,
            "sha256": sha256(artifact.read_bytes()).hexdigest(),
        },
        "stats": report.stats,
        "validation": {"result": "passed", "errors": 0},
        "completed_at": "2026-08-23T00:00:00+00:00",
    }
    provenance.write_text(json.dumps(payload), encoding="utf-8")
    source_files = {curated.name: curated, open_csv.name: open_csv}

    assert validate_provenance(provenance, artifact, report, source_files) == []

    artifact.write_text("tampered\n", encoding="utf-8")
    payload["source_files"][curated.name] = "0" * 64
    payload["stats"] = {"total": 2}
    payload["generator"]["model"] = "different-model"
    provenance.write_text(json.dumps(payload), encoding="utf-8")
    errors = validate_provenance(provenance, artifact, report, source_files)
    assert any("artifact sha256" in error for error in errors)
    assert any("source sha256" in error for error in errors)
    assert any("stats" in error for error in errors)
    assert any("generator model" in error for error in errors)
