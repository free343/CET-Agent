"""Deterministic spelling, vector, co-error, and temporal similarity."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.utils.datetime_utils import ensure_utc


def levenshtein_distance(first: str, second: str) -> int:
    """Return edit distance using O(min(m, n)) memory dynamic programming."""
    if first == second:
        return 0
    if len(first) < len(second):
        first, second = second, first
    if not second:
        return len(first)

    previous = list(range(len(second) + 1))
    for first_index, first_char in enumerate(first, start=1):
        current = [first_index]
        for second_index, second_char in enumerate(second, start=1):
            insertion = current[second_index - 1] + 1
            deletion = previous[second_index] + 1
            substitution = previous[second_index - 1] + (first_char != second_char)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def spelling_similarity(first: str, second: str) -> float:
    normalized_first = first.strip().lower()
    normalized_second = second.strip().lower()
    maximum_length = max(len(normalized_first), len(normalized_second))
    if maximum_length == 0:
        return 1.0
    distance = levenshtein_distance(normalized_first, normalized_second)
    return max(0.0, min(1.0, 1.0 - distance / maximum_length))


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    """Return non-negative cosine similarity in [0, 1].

    Text embedding spaces generally treat an orthogonal vector as unrelated.
    Mapping ``cosine == 0`` to 0.5 would give unrelated words a large semantic
    bonus, so negative values are clipped instead of shifted.
    """
    if len(first) != len(second) or not first:
        return 0.0
    dot_product = sum(a * b for a, b in zip(first, second, strict=True))
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0 or second_norm == 0:
        return 0.0
    raw_cosine = dot_product / (first_norm * second_norm)
    return max(0.0, min(1.0, raw_cosine))


def coerror_score(
    errors_a: Sequence[datetime],
    errors_b: Sequence[datetime],
    window: timedelta = timedelta(hours=24),
) -> float:
    """Measure one-to-one co-errors occurring within the configured window.

    Greedy matching prevents one error from inflating several co-error pairs,
    keeping the numerator bounded by min(error_a, error_b).
    """
    if not errors_a or not errors_b:
        return 0.0
    first = sorted(ensure_utc(value) for value in errors_a)
    second = sorted(ensure_utc(value) for value in errors_b)
    window_seconds = window.total_seconds()
    first_index = second_index = matches = 0
    while first_index < len(first) and second_index < len(second):
        delta = (first[first_index] - second[second_index]).total_seconds()
        if abs(delta) <= window_seconds:
            matches += 1
            first_index += 1
            second_index += 1
        elif delta < 0:
            first_index += 1
        else:
            second_index += 1
    return matches / max(1, min(len(first), len(second)))


def temporal_score(
    errors_a: Sequence[datetime],
    errors_b: Sequence[datetime],
    tau: timedelta = timedelta(hours=24),
) -> float:
    """Average exp(-delta/tau) using each error's nearest opposite error."""
    if not errors_a or not errors_b or tau.total_seconds() <= 0:
        return 0.0
    first = sorted(ensure_utc(value) for value in errors_a)
    second = sorted(ensure_utc(value) for value in errors_b)
    tau_seconds = tau.total_seconds()

    def nearest_decay(
        source: Sequence[datetime], target: Sequence[datetime]
    ) -> list[float]:
        scores: list[float] = []
        for item in source:
            insertion = bisect_left(target, item)
            neighbours = target[max(0, insertion - 1) : insertion + 1]
            nearest_seconds = min(
                abs((item - candidate).total_seconds()) for candidate in neighbours
            )
            scores.append(math.exp(-nearest_seconds / tau_seconds))
        return scores

    scores = nearest_decay(first, second) + nearest_decay(second, first)
    return max(0.0, min(1.0, sum(scores) / len(scores)))
