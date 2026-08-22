from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from app.domain.similarity import (
    coerror_score,
    cosine_similarity,
    levenshtein_distance,
    spelling_similarity,
    temporal_score,
)
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [("adapt", "adopt", 1), ("cat", "cat", 0), ("abc", "xyz", 3)],
)
def test_levenshtein_distance(first: str, second: str, expected: int) -> None:
    assert levenshtein_distance(first, second) == expected


def test_spelling_similarity_is_bounded_and_high_for_adapt_adopt() -> None:
    assert spelling_similarity("adapt", "adopt") == pytest.approx(0.8)
    assert spelling_similarity("", "") == 1.0
    assert spelling_similarity("abc", "xyz") == 0.0


def test_cosine_similarity_normalizes_to_zero_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(0.0)
    assert cosine_similarity([], []) == 0.0


def test_coerror_uses_one_to_one_matches() -> None:
    first = [NOW, NOW + timedelta(hours=2)]
    second = [NOW + timedelta(hours=1), NOW + timedelta(days=5)]
    assert coerror_score(first, second) == pytest.approx(0.5)


def test_temporal_score_prefers_close_errors() -> None:
    close = temporal_score([NOW], [NOW + timedelta(hours=1)])
    far = temporal_score([NOW], [NOW + timedelta(days=5)])
    assert 0.0 <= far < close <= 1.0


def test_temporal_score_matches_brute_force_for_unsorted_histories() -> None:
    first = [NOW + timedelta(hours=value) for value in (12, 0, 5, 2)]
    second = [NOW + timedelta(hours=value) for value in (9, 1, 20)]
    tau = timedelta(hours=24)

    def brute_force(source, target) -> list[float]:
        return [
            math.exp(
                -min(abs((item - candidate).total_seconds()) for candidate in target)
                / tau.total_seconds()
            )
            for item in source
        ]

    expected_scores = brute_force(first, second) + brute_force(second, first)
    expected = sum(expected_scores) / len(expected_scores)

    assert temporal_score(first, second, tau) == pytest.approx(expected)
