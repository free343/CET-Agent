"""Validated, idempotent import of bundled vocabulary CSV files."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LearningState, Word, WordLevel
from app.utils.datetime_utils import utc_now

_WORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
_REQUIRED_COLUMNS = {"word", "meaning", "level"}


class VocabularyDataError(ValueError):
    """Raised when a vocabulary source is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class VocabularySeedRow:
    word: str
    phonetic: str
    meaning: str
    example: str
    level: WordLevel
    frequency: int
    initial_delay_days: int


def load_vocabulary_rows(csv_path: Path) -> list[VocabularySeedRow]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Vocabulary source not found: {csv_path}")

    rows: list[VocabularySeedRow] = []
    seen: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = set(reader.fieldnames or ())
        missing_columns = sorted(_REQUIRED_COLUMNS - fieldnames)
        if missing_columns:
            raise VocabularyDataError(
                f"{csv_path.name} is missing columns: {', '.join(missing_columns)}"
            )

        for source_row in reader:
            line_number = reader.line_num
            word = (source_row.get("word") or "").strip().lower()
            if len(word) > 100 or _WORD_PATTERN.fullmatch(word) is None:
                raise VocabularyDataError(
                    f"{csv_path.name}:{line_number} has an invalid headword"
                )
            if word in seen:
                raise VocabularyDataError(
                    f"{csv_path.name}:{line_number} duplicates headword {word!r}"
                )

            meaning = (source_row.get("meaning") or "").strip()
            if not meaning:
                raise VocabularyDataError(
                    f"{csv_path.name}:{line_number} has an empty meaning"
                )
            phonetic = (source_row.get("phonetic") or "").strip()
            if len(phonetic) > 200:
                raise VocabularyDataError(
                    f"{csv_path.name}:{line_number} has an oversized phonetic value"
                )

            try:
                level = WordLevel((source_row.get("level") or "").strip().upper())
                frequency = _bounded_integer(
                    source_row.get("frequency"),
                    default=0,
                    minimum=0,
                    maximum=1_000_000,
                )
                initial_delay_days = _bounded_integer(
                    source_row.get("initial_delay_days"),
                    default=0,
                    minimum=0,
                    maximum=3_650,
                )
            except ValueError as exc:
                raise VocabularyDataError(
                    f"{csv_path.name}:{line_number} has invalid level or numeric data"
                ) from exc

            rows.append(
                VocabularySeedRow(
                    word=word,
                    phonetic=phonetic,
                    meaning=meaning,
                    example=(source_row.get("example") or "").strip(),
                    level=level,
                    frequency=frequency,
                    initial_delay_days=initial_delay_days,
                )
            )
            seen.add(word)

    if not rows:
        raise VocabularyDataError(f"{csv_path.name} contains no vocabulary rows")
    return rows


def seed_words(session: Session, csv_path: Path) -> int:
    rows = load_vocabulary_rows(csv_path)
    existing = {word.word: word for word in session.scalars(select(Word)).all()}
    inserted = 0
    seeded_at = utc_now()
    for row in rows:
        existing_word = existing.get(row.word)
        if existing_word is not None:
            existing_word.phonetic = row.phonetic
            existing_word.meaning = row.meaning
            existing_word.example = row.example
            existing_word.level = row.level
            existing_word.frequency = row.frequency
            continue
        word = Word(
            word=row.word,
            phonetic=row.phonetic,
            meaning=row.meaning,
            example=row.example,
            level=row.level,
            frequency=row.frequency,
        )
        word.learning_state = LearningState(
            next_review_at=seeded_at + timedelta(days=row.initial_delay_days)
        )
        session.add(word)
        existing[row.word] = word
        inserted += 1
    session.flush()
    return inserted


def ensure_learning_states(session: Session) -> int:
    words_without_state = session.scalars(
        select(Word).outerjoin(LearningState).where(LearningState.id.is_(None))
    )
    created = 0
    for word in words_without_state:
        session.add(LearningState(word_id=word.id, next_review_at=utc_now()))
        created += 1
    session.flush()
    return created


def _bounded_integer(
    raw_value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = default if raw_value is None or not raw_value.strip() else int(raw_value)
    if not minimum <= value <= maximum:
        raise ValueError("integer is outside its allowed range")
    return value
