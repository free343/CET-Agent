"""Reversible user-owned exclusion of completely mastered words."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db.database import Database
from app.db.models import MasteredWord, Word, WordLearningAid, WordLevel
from app.services.learning_aid_view import (
    resolve_example,
    resolve_example_translation,
)


@dataclass(frozen=True, slots=True)
class MasteredWordItem:
    word_id: int
    word: str
    phonetic: str
    meaning: str
    example: str
    level: WordLevel
    mastered_at: datetime
    example_translation: str = ""


@dataclass(frozen=True, slots=True)
class MasteryUpdate:
    word_id: int
    is_mastered: bool


class MasteryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_mastered(self, limit: int = 5_000) -> list[MasteredWordItem]:
        safe_limit = max(1, min(int(limit), 10_000))
        with self.database.session() as session:
            rows = session.execute(
                select(Word, MasteredWord.created_at, WordLearningAid)
                .join(MasteredWord, MasteredWord.word_id == Word.id)
                .outerjoin(WordLearningAid, WordLearningAid.word_id == Word.id)
                .order_by(MasteredWord.created_at.desc(), Word.word.asc())
                .limit(safe_limit)
            ).all()
            return [
                MasteredWordItem(
                    word_id=word.id,
                    word=word.word,
                    phonetic=word.phonetic,
                    meaning=word.meaning,
                    example=resolve_example(word.example, aid),
                    level=word.level,
                    mastered_at=mastered_at,
                    example_translation=resolve_example_translation(aid),
                )
                for word, mastered_at, aid in rows
            ]

    def set_mastered(self, word_id: int, mastered: bool) -> MasteryUpdate:
        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            word = session.get(Word, word_id)
            if word is None:
                raise LookupError(f"No word for word_id={word_id}")
            marker = session.get(MasteredWord, word_id)
            if mastered and marker is None:
                session.add(MasteredWord(word_id=word_id))
            elif not mastered and marker is not None:
                session.delete(marker)
        return MasteryUpdate(word_id=word_id, is_mastered=mastered)
