from __future__ import annotations

from app.domain.meaning_quiz import MeaningCandidate, build_meaning_options


def test_meaning_options_are_deterministic_unique_and_include_target() -> None:
    target = MeaningCandidate(1, "n. 状态, 情形", 100, review_count=3)
    candidates = [
        target,
        MeaningCandidate(2, "n. 系统, 体系", 99),
        MeaningCandidate(3, "n. 政府, 内阁", 97),
        MeaningCandidate(4, "v. 采用, 收养", 98),
        MeaningCandidate(5, "n. 区域, 面积", 90),
        MeaningCandidate(6, "n. 状态, 情形", 101),
    ]

    first = build_meaning_options(target, candidates)
    second = build_meaning_options(target, candidates)

    assert first == second
    assert len(first) == 4
    assert sum(option.word_id == target.word_id for option in first) == 1
    assert sum(option.is_correct for option in first) == 1
    assert len({option.meaning for option in first}) == 4
    assert 4 not in {option.word_id for option in first}


def test_meaning_options_degrade_when_reliable_distractors_are_insufficient() -> None:
    target = MeaningCandidate(1, "适应", 100)

    assert (
        build_meaning_options(
            target,
            [target, MeaningCandidate(2, "采用", 90)],
        )
        == ()
    )
