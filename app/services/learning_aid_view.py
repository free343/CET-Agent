"""Deterministic mapping of WordLearningAid rows into bounded display values.

This module owns the JSON-to-display formatting so the UI layer never parses
raw JSON, never touches SQLAlchemy, and never calls a concrete model adapter.
Every return value is an immutable, bounded tuple of pre-formatted strings.
"""

from __future__ import annotations

import json

from app.db.models import WordLearningAid

_COLLOCATION_LIMIT = 4
_WORD_FAMILY_LIMIT = 4


def resolve_example(word_example: str, aid: WordLearningAid | None) -> str:
    """Curated words keep their CSV example; open words use the validated aid."""
    if word_example:
        return word_example
    if aid is not None and aid.example:
        return aid.example
    return ""


def resolve_example_translation(aid: WordLearningAid | None) -> str:
    if aid is None:
        return ""
    return aid.example_translation


def format_collocations(aid: WordLearningAid | None) -> tuple[str, ...]:
    """Map stored collocations to ``英文搭配｜中文义`` display strings."""
    if aid is None:
        return ()
    try:
        items = json.loads(aid.collocations_json)
    except (TypeError, ValueError):
        return ()
    if not isinstance(items, list):
        return ()
    return tuple(
        f"{item['phrase']}｜{item['meaning']}"
        for item in items[:_COLLOCATION_LIMIT]
        if isinstance(item, dict)
        and str(item.get("phrase") or "").strip()
        and str(item.get("meaning") or "").strip()
    )


def format_word_family(aid: WordLearningAid | None) -> tuple[str, ...]:
    """Map stored word family to ``单词 (词性)｜中文义`` display strings."""
    if aid is None:
        return ()
    try:
        items = json.loads(aid.word_family_json)
    except (TypeError, ValueError):
        return ()
    if not isinstance(items, list):
        return ()
    return tuple(
        f"{item['word']} ({item['part_of_speech']})｜{item['meaning']}"
        for item in items[:_WORD_FAMILY_LIMIT]
        if isinstance(item, dict)
        and str(item.get("word") or "").strip()
        and str(item.get("meaning") or "").strip()
    )
