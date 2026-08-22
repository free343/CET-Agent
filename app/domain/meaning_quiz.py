"""Deterministic Chinese-meaning choices for vocabulary review."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeaningCandidate:
    word_id: int
    meaning: str
    frequency: int
    review_count: int = 0


@dataclass(frozen=True, slots=True)
class MeaningOption:
    word_id: int
    meaning: str
    is_correct: bool


def build_meaning_options(
    target: MeaningCandidate,
    candidates: list[MeaningCandidate],
    *,
    option_count: int = 4,
) -> tuple[MeaningOption, ...]:
    """Return one correct meaning and reliable deterministic distractors."""

    if option_count < 2:
        raise ValueError("option_count must be at least 2")
    target_meaning = _normalize_meaning(target.meaning)
    if not target_meaning:
        return ()

    target_tags = _part_of_speech_tags(target.meaning)
    unique_candidates: dict[str, MeaningCandidate] = {}
    for candidate in candidates:
        normalized = _normalize_meaning(candidate.meaning)
        if (
            candidate.word_id == target.word_id
            or not normalized
            or normalized == target_meaning
        ):
            continue
        existing = unique_candidates.get(normalized)
        if existing is None or _candidate_rank(
            target, target_tags, candidate
        ) < _candidate_rank(target, target_tags, existing):
            unique_candidates[normalized] = candidate

    ranked = sorted(
        unique_candidates.values(),
        key=lambda candidate: _candidate_rank(target, target_tags, candidate),
    )
    if len(ranked) < option_count - 1:
        return ()

    selected = [target, *ranked[: option_count - 1]]
    selected.sort(
        key=lambda candidate: _stable_number(
            f"choice-order:{target.word_id}:{target.review_count}:{candidate.word_id}"
        )
    )
    return tuple(
        MeaningOption(
            word_id=candidate.word_id,
            meaning=candidate.meaning,
            is_correct=candidate.word_id == target.word_id,
        )
        for candidate in selected
    )


def _candidate_rank(
    target: MeaningCandidate,
    target_tags: frozenset[str],
    candidate: MeaningCandidate,
) -> tuple[int, int, int]:
    candidate_tags = _part_of_speech_tags(candidate.meaning)
    part_of_speech_penalty = int(
        bool(target_tags) and not bool(target_tags & candidate_tags)
    )
    return (
        part_of_speech_penalty,
        abs(target.frequency - candidate.frequency),
        _stable_number(f"choice-rank:{target.word_id}:{candidate.word_id}"),
    )


def _normalize_meaning(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _part_of_speech_tags(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return frozenset(re.findall(r"(?:^|[；;])\s*([a-z]+)\.", normalized))


def _stable_number(value: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(),
        byteorder="big",
    )
