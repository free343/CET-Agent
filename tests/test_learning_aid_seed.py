"""Deterministic tests for the learning-aid import service and view mapping."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai.learning_aid_validation import SourceEntry
from app.db.learning_aid_seed import (
    LearningAidDataError,
    content_hash,
    load_learning_aid_records,
    seed_learning_aids,
)
from app.db.models import LearningState, Word, WordLearningAid, WordLevel
from app.services.learning_aid_view import (
    format_collocations,
    format_word_family,
    resolve_example,
    resolve_example_translation,
)
from app.services.review_service import ReviewService
from app.services.wordbook_service import WordbookService
from app.utils.datetime_utils import UTC


def _record(
    word,
    *,
    example,
    translation="翻译",
    collocations=None,
    word_family=None,
    model="deepseek-chat",
) -> dict:
    return {
        "schema_version": 1,
        "word": word,
        "level": "CET4",
        "source_kind": "open",
        "source_meaning": f"{word} 的释义",
        "example": example,
        "example_translation": translation,
        "example_origin": "ai_generated",
        "collocations": collocations
        if collocations is not None
        else [
            {"phrase": f"{word} phrase", "meaning": "搭配一"},
            {"phrase": f"common {word}", "meaning": "搭配二"},
        ],
        "word_family": word_family
        if word_family is not None
        else [
            {
                "word": "adaptable",
                "part_of_speech": "adj.",
                "meaning": "适应性强的",
                "relation": "derivative",
            },
        ],
        "generator": {
            "provider": "deepseek",
            "model": model,
            "prompt_version": "word-learning-aids-v1",
        },
        "content_status": "ai_generated_unreviewed",
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _add_open_word(database, word: str, *, due: bool = True) -> int:
    with database.session() as session:
        model = Word(
            word=word,
            meaning=f"{word} 的释义",
            example="",
            level=WordLevel.CET4,
        )
        model.learning_state = LearningState(
            next_review_at=datetime(2026, 1, 1, tzinfo=UTC)
            if due
            else datetime(2027, 1, 1, tzinfo=UTC)
        )
        session.add(model)
        session.flush()
        return model.id


def test_missing_file_loads_no_records(tmp_path) -> None:
    assert load_learning_aid_records(tmp_path / "missing.jsonl") == []


def test_malformed_file_is_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("this is not json\n", encoding="utf-8")
    with pytest.raises(LearningAidDataError):
        load_learning_aid_records(bad)


def test_strict_load_rejects_source_mismatch_before_database_write(tmp_path) -> None:
    jsonl = tmp_path / "aids.jsonl"
    _write_jsonl(
        jsonl,
        [
            _record(
                "adapt",
                example="Students carefully adapt to new situations today.",
            )
        ],
    )
    source = SourceEntry(
        word="adapt",
        level="CET4",
        meaning="来自 CSV 的真实释义",
        example="",
        source_kind="open",
    )

    with pytest.raises(LearningAidDataError, match="source_meaning"):
        load_learning_aid_records(
            jsonl,
            ordered_sources=[source],
            require_complete=True,
        )


def test_seed_matches_words_and_never_creates_new_ones(database, tmp_path) -> None:
    _add_open_word(database, "adapt")
    jsonl = tmp_path / "aids.jsonl"
    _write_jsonl(
        jsonl,
        [
            _record("adapt", example="Adapt is here."),
            _record("ghost", example="Ghost is here."),
        ],
    )

    records = load_learning_aid_records(jsonl)
    with database.session() as session:
        written = seed_learning_aids(session, records)

    assert written == 1
    with database.session() as session:
        assert session.scalar(select(Word).where(Word.word == "ghost")) is None
        aid = session.scalar(
            select(WordLearningAid).where(
                WordLearningAid.word_id
                == session.scalar(select(Word.id).where(Word.word == "adapt"))
            )
        )
        assert aid is not None
        assert aid.example == "Adapt is here."


def test_seed_is_idempotent_and_hash_aware(database, tmp_path) -> None:
    _add_open_word(database, "adapt")
    jsonl = tmp_path / "aids.jsonl"
    _write_jsonl(jsonl, [_record("adapt", example="Adapt is here.")])

    records = load_learning_aid_records(jsonl)
    with database.session() as session:
        assert seed_learning_aids(session, records) == 1
    with database.session() as session:
        assert seed_learning_aids(session, records) == 0

    _write_jsonl(jsonl, [_record("adapt", example="A new adapt example.")])
    updated = load_learning_aid_records(jsonl)
    with database.session() as session:
        assert seed_learning_aids(session, updated) == 1
    with database.session() as session:
        word_id = session.scalar(select(Word.id).where(Word.word == "adapt"))
        aid = session.get(WordLearningAid, word_id)
        assert aid is not None and aid.example == "A new adapt example."


def test_content_hash_is_stable_and_sensitive() -> None:
    record = _record("adapt", example="Adapt is here.")
    from app.ai.schemas import WordLearningAidRecord

    model = WordLearningAidRecord.model_validate(record)
    assert content_hash(model) == content_hash(
        WordLearningAidRecord.model_validate(record)
    )
    changed = dict(record, example="A different adapt example.")
    assert content_hash(model) != content_hash(
        WordLearningAidRecord.model_validate(changed)
    )


def test_view_maps_collocations_and_word_family() -> None:
    aid = WordLearningAid(
        collocations_json=json.dumps(
            [
                {"phrase": "adapt to", "meaning": "适应"},
                {"phrase": "adapt a book", "meaning": "改编一本书"},
            ],
            ensure_ascii=False,
        ),
        word_family_json=json.dumps(
            [
                {
                    "word": "adaptable",
                    "part_of_speech": "adj.",
                    "meaning": "适应性强的",
                    "relation": "derivative",
                }
            ],
            ensure_ascii=False,
        ),
    )
    assert format_collocations(aid) == ("adapt to｜适应", "adapt a book｜改编一本书")
    assert format_word_family(aid) == ("adaptable (adj.)｜适应性强的",)


def test_view_ignores_malformed_json() -> None:
    aid = WordLearningAid(
        collocations_json="not json",
        word_family_json='[{"word":',
    )
    assert format_collocations(aid) == ()
    assert format_word_family(aid) == ()


def test_review_service_maps_validated_aid(database) -> None:
    word_id = _add_open_word(database, "adapt")
    with database.session() as session:
        aid = WordLearningAid(
            word_id=word_id,
            example="Students adapt to new environments.",
            example_translation="学生适应新的环境。",
            collocations_json=json.dumps(
                [{"phrase": "adapt to", "meaning": "适应"}], ensure_ascii=False
            ),
            word_family_json=json.dumps(
                [
                    {
                        "word": "adaptable",
                        "part_of_speech": "adj.",
                        "meaning": "适应性强的",
                        "relation": "derivative",
                    }
                ],
                ensure_ascii=False,
            ),
            generator="deepseek",
            model="deepseek-chat",
            prompt_version="word-learning-aids-v1",
            content_status="ai_generated_unreviewed",
            content_hash="abc",
        )
        session.add(aid)

    item = ReviewService(database).get_due_words()[0]
    assert item.example == "Students adapt to new environments."
    assert item.example_translation == "学生适应新的环境。"
    assert item.collocations == ("adapt to｜适应",)
    assert item.word_family == ("adaptable (adj.)｜适应性强的",)


def test_review_service_prefers_curated_word_example(database, word_id) -> None:
    # word_id fixture has example "Students adapt quickly."
    with database.session() as session:
        aid = WordLearningAid(
            word_id=word_id,
            example="Generated example should not win.",
            example_translation="生成翻译",
            collocations_json="[]",
            word_family_json="[]",
            generator="deepseek",
            model="deepseek-chat",
            prompt_version="word-learning-aids-v1",
            content_status="ai_generated_unreviewed",
            content_hash="abc",
        )
        session.add(aid)

    item = ReviewService(database).get_due_words()[0]
    assert item.example == "Students adapt quickly."
    assert item.example_translation == "生成翻译"


def test_wordbook_service_maps_aid_example_and_translation(database) -> None:
    word_id = _add_open_word(database, "adapt")
    with database.session() as session:
        session.add(
            WordLearningAid(
                word_id=word_id,
                example="Students adapt quickly here.",
                example_translation="学生很快适应。",
                collocations_json="[]",
                word_family_json="[]",
                generator="deepseek",
                model="deepseek-chat",
                prompt_version="word-learning-aids-v1",
                content_status="ai_generated_unreviewed",
                content_hash="abc",
            )
        )

    service = WordbookService(database)
    service.set_favorite(word_id, True)
    items = service.list_favorites()
    assert len(items) == 1
    assert items[0].example == "Students adapt quickly here."
    assert items[0].example_translation == "学生很快适应。"


def test_empty_aid_degrades_to_placeholders() -> None:
    assert resolve_example("", None) == ""
    assert resolve_example_translation(None) == ""
    assert format_collocations(None) == ()
    assert format_word_family(None) == ()
