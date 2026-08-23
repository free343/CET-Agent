from __future__ import annotations

from app.db.models import WordLevel
from app.domain.acquisition import (
    EnglishCandidate,
    advance_proficiency,
    build_cloze_question,
    spelling_matches,
)


def _candidate(word_id: int, word: str, meaning: str = "n. 词") -> EnglishCandidate:
    return EnglishCandidate(
        word_id=word_id,
        word=word,
        meaning=meaning,
        frequency=100 - word_id,
    )


def test_proficiency_advances_only_one_level_when_correct() -> None:
    assert [advance_proficiency(level, is_correct=True) for level in range(3)] == [
        1,
        2,
        3,
    ]
    assert [advance_proficiency(level, is_correct=False) for level in range(3)] == [
        0,
        1,
        2,
    ]


def test_spelling_uses_nfkc_casefold_and_whitespace_normalization() -> None:
    assert spelling_matches("  ＡＤＡＰＴ\n", "adapt") is True
    assert spelling_matches("adopt", "adapt") is False


def test_cloze_question_hides_target_and_has_one_stable_correct_choice() -> None:
    target = _candidate(1, "adapt", "v. 适应")
    candidates = [
        target,
        _candidate(2, "adopt", "v. 采用"),
        _candidate(3, "adept", "a. 熟练的"),
        _candidate(4, "accept", "v. 接受"),
        _candidate(5, "adjust", "v. 调整"),
    ]
    question = build_cloze_question(
        target,
        "Students adapted quickly to the new environment.",
        candidates,
    )

    assert question is not None
    assert "adapt" not in question.text.casefold()
    assert len(question.options) == 4
    assert sum(option.is_correct for option in question.options) == 1
    assert next(option for option in question.options if option.is_correct).text == (
        "adapted"
    )
    assert question == build_cloze_question(
        target,
        "Students adapted quickly to the new environment.",
        candidates,
    )


def test_cloze_question_returns_none_without_four_reliable_choices() -> None:
    target = _candidate(1, "adapt", "v. 适应")
    assert (
        build_cloze_question(
            target,
            "Students adapt quickly.",
            [target, _candidate(2, "adopt")],
        )
        is None
    )


def test_candidate_levels_are_plain_values() -> None:
    assert WordLevel.CET4.value == "CET4"
