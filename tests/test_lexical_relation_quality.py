"""Regression tests for learner-facing relation translation gates."""

from __future__ import annotations

from app.domain.lexical_relation_quality import (
    has_learner_translation,
    learner_translation,
    relation_translation_flags,
    translation_matches_sense,
)
from app.domain.lexical_source_readers import ECDICTEntry


def _entry(translation: str) -> ECDICTEntry:
    return ECDICTEntry("", translation, "", {}, 0)


def test_specialist_only_translation_is_not_learner_gloss() -> None:
    entry = _entry(r"[化] 最高占据轨道; 最高占据分子轨道\n[医] 人属")

    assert not has_learner_translation(entry, part_of_speech="n")
    assert relation_translation_flags("人；人类", entry, relation_type="synonym") == (
        "domain_only_translation",
    )


def test_mixed_domain_segments_keep_only_the_ordinary_gloss() -> None:
    entry = _entry("n. 人；n. [医] 人属")

    assert learner_translation(entry.translation, part_of_speech="n") == "人"


def test_translation_is_filtered_to_the_relation_part_of_speech() -> None:
    entry = _entry("n. 人；人类\nv. 使用；操作")

    assert learner_translation(entry.translation, part_of_speech="n") == "人；人类"
    assert learner_translation(entry.translation, part_of_speech="v") == "使用；操作"


def test_one_character_substrings_do_not_fake_a_synonym_match() -> None:
    entry = _entry("n. 人属")

    assert not translation_matches_sense("人；人类", entry)
    assert relation_translation_flags("人；人类", entry, relation_type="synonym") == (
        "sense_translation_mismatch",
    )
