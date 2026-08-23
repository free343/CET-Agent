"""Deterministic tasks and grading for pre-FSRS word acquisition."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from app.db.models import AcquisitionTaskType


@dataclass(frozen=True, slots=True)
class EnglishCandidate:
    word_id: int
    word: str
    meaning: str
    frequency: int


@dataclass(frozen=True, slots=True)
class EnglishOption:
    word_id: int
    text: str
    is_correct: bool


@dataclass(frozen=True, slots=True)
class ClozeQuestion:
    text: str
    options: tuple[EnglishOption, ...]


_IRREGULAR_PAST_FORMS = {
    "fling": "flung",
}


def task_for_level(level: int, *, self_confirmed: bool = False) -> AcquisitionTaskType:
    if level == 0:
        return AcquisitionTaskType.MEANING_CHOICE
    if level == 1:
        return AcquisitionTaskType.CLOZE_CHOICE
    if level == 2:
        return (
            AcquisitionTaskType.SELF_CONFIRM
            if self_confirmed
            else AcquisitionTaskType.SPELLING
        )
    raise ValueError("Acquisition level must be between 0 and 2")


def advance_proficiency(level: int, *, is_correct: bool) -> int:
    if not 0 <= level <= 2:
        raise ValueError("Acquisition level must be between 0 and 2")
    return level + 1 if is_correct else level


def spelling_matches(answer: str, expected: str) -> bool:
    return _normalize_spelling(answer) == _normalize_spelling(expected)


def build_cloze_question(
    target: EnglishCandidate,
    example: str,
    candidates: list[EnglishCandidate],
    *,
    option_count: int = 4,
) -> ClozeQuestion | None:
    """Hide the target form and return four deterministic English choices."""

    if option_count < 2:
        raise ValueError("option_count must be at least 2")
    match = _find_target_form(target.word, example)
    if match is None:
        return None
    _start, _end, surface, inflection = match
    hidden = mask_target_forms(target.word, example)
    target_tags = _part_of_speech_tags(target.meaning)
    ranked = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.word_id != target.word_id and candidate.word.strip()
        ),
        key=lambda candidate: (
            int(
                bool(target_tags)
                and not bool(target_tags & _part_of_speech_tags(candidate.meaning))
            ),
            abs(len(candidate.word) - len(target.word)),
            abs(candidate.frequency - target.frequency),
            _stable_number(f"cloze-rank:{target.word_id}:{candidate.word_id}"),
        ),
    )
    selected: list[EnglishCandidate] = [target]
    seen = {_normalize_spelling(surface)}
    option_text_by_id = {target.word_id: surface.casefold()}
    for candidate in ranked:
        transformed = _apply_inflection(candidate.word, inflection)
        normalized = _normalize_spelling(transformed)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        selected.append(candidate)
        option_text_by_id[candidate.word_id] = transformed.casefold()
        if len(selected) == option_count:
            break
    if len(selected) != option_count:
        return None
    selected.sort(
        key=lambda candidate: _stable_number(
            f"cloze-order:{target.word_id}:{candidate.word_id}"
        )
    )
    return ClozeQuestion(
        text=hidden,
        options=tuple(
            EnglishOption(
                word_id=candidate.word_id,
                text=option_text_by_id[candidate.word_id],
                is_correct=candidate.word_id == target.word_id,
            )
            for candidate in selected
        ),
    )


def _find_target_form(
    word: str,
    example: str,
) -> tuple[int, int, str, str] | None:
    matches: list[tuple[int, int, str, str]] = []
    for surface, inflection in _regular_forms(word):
        for match in re.finditer(
            rf"(?<![A-Za-z]){re.escape(surface)}(?![A-Za-z])",
            example,
            flags=re.IGNORECASE,
        ):
            matches.append((match.start(), match.end(), match.group(0), inflection))
    return min(matches, key=lambda item: item[0]) if matches else None


def mask_target_forms(word: str, example: str) -> str:
    forms = sorted(
        {surface for surface, _inflection in _regular_forms(word)},
        key=len,
        reverse=True,
    )
    pattern = re.compile(
        rf"(?<![A-Za-z])(?:{'|'.join(re.escape(form) for form in forms)})(?![A-Za-z])",
        flags=re.IGNORECASE,
    )
    return pattern.sub(lambda match: "_" * max(6, len(match.group(0))), example)


def _regular_forms(word: str) -> tuple[tuple[str, str], ...]:
    normalized = word.casefold()
    forms: list[tuple[str, str]] = [(normalized, "base")]
    irregular_past = _IRREGULAR_PAST_FORMS.get(normalized)
    if irregular_past is not None:
        forms.append((irregular_past, "past_irregular"))
    if normalized.endswith("e"):
        forms.extend(((f"{normalized}d", "past_e"), (f"{normalized[:-1]}ing", "ing_e")))
    else:
        forms.extend(((f"{normalized}ed", "past"), (f"{normalized}ing", "ing")))
    if (
        len(normalized) > 2
        and normalized.endswith("y")
        and normalized[-2] not in "aeiou"
    ):
        forms.extend(
            ((f"{normalized[:-1]}ies", "ies"), (f"{normalized[:-1]}ied", "ied"))
        )
    elif normalized.endswith(("s", "x", "z", "ch", "sh")):
        forms.append((f"{normalized}es", "es"))
    else:
        forms.append((f"{normalized}s", "s"))
    if _ends_in_cvc(normalized):
        forms.extend(
            (
                (f"{normalized}{normalized[-1]}ed", "past_double"),
                (f"{normalized}{normalized[-1]}ing", "ing_double"),
            )
        )
    return tuple(sorted(set(forms), key=lambda item: (-len(item[0]), item[1])))


def _apply_inflection(word: str, inflection: str) -> str:
    normalized = word.casefold()
    if inflection == "base":
        return normalized
    if inflection == "past_e":
        return f"{normalized}d" if normalized.endswith("e") else f"{normalized}ed"
    if inflection == "ing_e":
        return (
            f"{normalized[:-1]}ing" if normalized.endswith("e") else f"{normalized}ing"
        )
    if inflection == "past":
        return f"{normalized}ed"
    if inflection == "ing":
        return f"{normalized}ing"
    if inflection == "ies":
        return (
            f"{normalized[:-1]}ies"
            if normalized.endswith("y") and len(normalized) > 1
            else f"{normalized}s"
        )
    if inflection == "ied":
        return (
            f"{normalized[:-1]}ied"
            if normalized.endswith("y") and len(normalized) > 1
            else f"{normalized}ed"
        )
    if inflection == "es":
        return f"{normalized}es"
    if inflection == "s":
        return f"{normalized}s"
    if inflection == "past_double":
        return (
            f"{normalized}{normalized[-1]}ed"
            if _ends_in_cvc(normalized)
            else f"{normalized}ed"
        )
    if inflection == "ing_double":
        return (
            f"{normalized}{normalized[-1]}ing"
            if _ends_in_cvc(normalized)
            else f"{normalized}ing"
        )
    if inflection == "past_irregular":
        return _IRREGULAR_PAST_FORMS.get(normalized, f"{normalized}ed")
    raise ValueError(f"Unsupported inflection: {inflection}")


def _ends_in_cvc(word: str) -> bool:
    return (
        len(word) >= 3
        and word[-1] not in "aeiouwxy"
        and word[-2] in "aeiou"
        and word[-3] not in "aeiou"
    )


def _normalize_spelling(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def _part_of_speech_tags(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return frozenset(re.findall(r"(?:^|[；;])\s*([a-z]+)\.", normalized))


def _stable_number(value: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(),
        byteorder="big",
    )
