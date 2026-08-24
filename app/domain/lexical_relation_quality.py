"""Deterministic learner-facing quality gates for relation translations.

ECDICT contains both ordinary learner translations and entries that only make
sense inside a specialist domain (for example, ``[医] 人属`` for ``homo``).
WordNet supplies the relation topology, but it does not tell us whether the
Chinese gloss is suitable for a CET word card.  This module keeps that small
quality decision deterministic and replayable; it does not call an LLM.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.domain.lexical_source_readers import ECDICTEntry

_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")
_DOMAIN_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]{1,24}\]|【[^】]{1,24}】|\([^)]{1,24}\))\s*"
)
_POS_PREFIX = re.compile(
    r"^\s*(adv|vt|vi|aux|prep|pron|conj|v|n|a|s|num|art)\.\s*",
    re.IGNORECASE,
)
_TRANSLATION_SEPARATOR = re.compile(r"[;；]+")
MAX_LEARNER_TRANSLATION_CHARS = 120


@dataclass(frozen=True, slots=True)
class TranslationSegment:
    """One bounded ECDICT translation segment after prefix normalization."""

    text: str
    chinese: str
    domain_tagged: bool
    part_of_speech: str = ""


def translation_segments(raw: str) -> tuple[TranslationSegment, ...]:
    """Return normalized Chinese translation segments from an ECDICT field.

    ECDICT stores literal ``\\n`` escapes in some releases, so both escaped and
    physical line breaks are accepted.  Domain markers are retained as metadata
    and removed from the learner-facing text rather than being mistaken for a
    translation.
    """

    normalized = unicodedata.normalize("NFKC", raw or "").replace("\\n", "\n")
    segments: list[TranslationSegment] = []
    for raw_line in normalized.splitlines() or [normalized]:
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        domain_tagged = False
        while True:
            match = _DOMAIN_PREFIX.match(line)
            if match is None:
                break
            domain_tagged = True
            line = line[match.end() :].strip()
        inherited_part_of_speech = ""
        for raw_segment in _TRANSLATION_SEPARATOR.split(line):
            segment = raw_segment.strip()
            segment_domain_tagged = domain_tagged
            while True:
                segment_domain_match = _DOMAIN_PREFIX.match(segment)
                if segment_domain_match is None:
                    break
                segment_domain_tagged = True
                segment = segment[segment_domain_match.end() :].strip()
            pos_match = _POS_PREFIX.match(segment)
            if pos_match:
                inherited_part_of_speech = pos_match.group(1).casefold()
            part_of_speech = inherited_part_of_speech
            value = _POS_PREFIX.sub("", segment).strip()
            while True:
                value_domain_match = _DOMAIN_PREFIX.match(value)
                if value_domain_match is None:
                    break
                segment_domain_tagged = True
                value = value[value_domain_match.end() :].strip()
            chinese = "".join(_CHINESE_RUN.findall(value))
            if not chinese:
                continue
            segments.append(
                TranslationSegment(
                    text=value,
                    chinese=chinese,
                    domain_tagged=segment_domain_tagged,
                    part_of_speech=part_of_speech,
                )
            )
    return tuple(segments)


def learner_translation(raw: str, *, part_of_speech: str | None = None) -> str:
    """Return compact ordinary-language Chinese suitable for a word card.

    Specialist-only entries intentionally return an empty string.  This is a
    hard display gate: a relation target with no ordinary gloss is not emitted
    into the candidate overlay.  Domain-tagged alternatives are omitted even
    when a row also contains ordinary alternatives, keeping cards concise.
    """

    segments = translation_segments(raw)
    if part_of_speech:
        matching = [
            segment
            for segment in segments
            if not segment.domain_tagged
            and (
                not segment.part_of_speech
                or _part_of_speech_matches(segment.part_of_speech, part_of_speech)
            )
        ]
        # If the source row carries POS prefixes but none match the WordNet
        # sense, do not silently fall back to a different grammatical sense.
        segments = tuple(matching)
    values: list[str] = []
    for segment in segments:
        if segment.domain_tagged:
            continue
        text = segment.text
        if text and text not in values:
            values.append(text)
    return "；".join(values)[:MAX_LEARNER_TRANSLATION_CHARS]


def has_learner_translation(
    entry: ECDICTEntry, *, part_of_speech: str | None = None
) -> bool:
    """Whether an ECDICT row has at least one ordinary-language gloss."""

    return bool(learner_translation(entry.translation, part_of_speech=part_of_speech))


def translation_matches_sense(source_sense: str, entry: ECDICTEntry) -> bool:
    """Check conservative Chinese overlap for a synonym audit.

    One-character Chinese fragments are matched only exactly; allowing a
    one-character substring would classify ``人属`` as the everyday sense
    ``人`` and recreate the ``human → homo`` bug.  This check is diagnostic for
    antonyms because an antonym is expected to have a different gloss.
    """

    source_segments = _CHINESE_RUN.findall(
        unicodedata.normalize("NFKC", source_sense or "")
    )
    target_segments = [
        segment.chinese
        for segment in translation_segments(entry.translation)
        if not segment.domain_tagged
    ]
    for source in source_segments:
        for target in target_segments:
            if source == target:
                return True
            if (
                len(source) >= 2
                and len(target) >= 2
                and (source in target or target in source)
            ):
                return True
    return False


def relation_translation_flags(
    source_sense: str,
    entry: ECDICTEntry,
    *,
    relation_type: str,
) -> tuple[str, ...]:
    """Return deterministic audit flags without changing source data."""

    segments = translation_segments(entry.translation)
    if not segments:
        return ("missing_translation",)
    ordinary = [segment for segment in segments if not segment.domain_tagged]
    if not ordinary:
        return ("domain_only_translation",)
    if relation_type == "synonym" and not translation_matches_sense(
        source_sense, entry
    ):
        return ("sense_translation_mismatch",)
    return ()


def _part_of_speech_matches(observed: str, expected: str) -> bool:
    observed = observed.casefold()
    expected = expected.casefold()
    if expected in {"a", "adjective"}:
        return observed in {"a", "s", "adv"}
    if expected in {"r", "adverb"}:
        return observed in {"adv", "a"}
    if expected in {"n", "noun"}:
        return observed == "n"
    if expected in {"v", "verb"}:
        return observed in {"v", "vt", "vi"}
    return True
