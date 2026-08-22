"""Persistent personal wordbook use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db.database import Database
from app.db.models import FavoriteWord, Word, WordLearningAid, WordLevel
from app.services.learning_aid_view import (
    resolve_example,
    resolve_example_translation,
)


@dataclass(frozen=True, slots=True)
class FavoriteWordItem:
    word_id: int
    word: str
    phonetic: str
    meaning: str
    example: str
    level: WordLevel
    created_at: datetime
    example_translation: str = ""


@dataclass(frozen=True, slots=True)
class FavoriteUpdate:
    word_id: int
    is_favorite: bool


class WordbookService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_favorites(self, limit: int = 5_000) -> list[FavoriteWordItem]:
        safe_limit = max(1, min(int(limit), 10_000))
        with self.database.session() as session:
            rows = session.execute(
                select(Word, FavoriteWord.created_at, WordLearningAid)
                .join(FavoriteWord, FavoriteWord.word_id == Word.id)
                .outerjoin(WordLearningAid, WordLearningAid.word_id == Word.id)
                .order_by(FavoriteWord.created_at.desc(), Word.word.asc())
                .limit(safe_limit)
            ).all()
            return [
                FavoriteWordItem(
                    word_id=word.id,
                    word=word.word,
                    phonetic=word.phonetic,
                    meaning=word.meaning,
                    example=resolve_example(word.example, aid),
                    level=word.level,
                    created_at=created_at,
                    example_translation=resolve_example_translation(aid),
                )
                for word, created_at, aid in rows
            ]

    def set_favorite(self, word_id: int, favorite: bool) -> FavoriteUpdate:
        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            word = session.get(Word, word_id)
            if word is None:
                raise LookupError(f"No word for word_id={word_id}")
            entry = session.get(FavoriteWord, word_id)
            if favorite and entry is None:
                session.add(FavoriteWord(word_id=word_id))
            elif not favorite and entry is not None:
                session.delete(entry)
        return FavoriteUpdate(word_id=word_id, is_favorite=favorite)
