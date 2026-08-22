"""Idempotent import of the bundled sample vocabulary."""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LearningState, Word, WordLevel
from app.utils.datetime_utils import utc_now


def seed_words(session: Session, csv_path: Path) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"Sample vocabulary not found: {csv_path}")

    existing = set(session.scalars(select(Word.word)))
    inserted = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            normalized = row["word"].strip().lower()
            if not normalized or normalized in existing:
                continue
            word = Word(
                word=normalized,
                phonetic=row.get("phonetic", "").strip(),
                meaning=row["meaning"].strip(),
                example=row.get("example", "").strip(),
                level=WordLevel(row["level"].strip().upper()),
                frequency=int(row.get("frequency", 0) or 0),
            )
            word.learning_state = LearningState(next_review_at=utc_now())
            session.add(word)
            existing.add(normalized)
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

