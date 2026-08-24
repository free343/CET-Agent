"""Read-only word-card lookup for linked lexical targets."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import case, func, select

from app.db.database import Database
from app.db.models import (
    Word,
    WordLearningAid,
    WordLearningAidFeedback,
    WordLexicalFact,
)
from app.services.learning_aid_view import (
    resolve_example,
    resolve_example_translation,
)
from app.services.lexical_fact_view import (
    LexicalFactSection,
    LinkedWordReference,
    build_lexical_facts_view,
)

_HEADWORD_PATTERN = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
_SEARCH_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'-]{0,99}$")


@dataclass(frozen=True, slots=True)
class WordDetailView:
    """Bounded content rendered by the read-only detail dialog."""

    reference: LinkedWordReference
    word: str
    phonetic: str
    meaning: str
    level: str
    example: str
    example_translation: str
    sections: tuple[LexicalFactSection, ...]
    reference_only: bool = False

    @property
    def trust_label(self) -> str:
        if not self.reference_only:
            return ""
        if self.reference.trust == "source_candidate":
            return "来源候选 · 待审核 · 词库外参考"
        if self.reference.trust == "ai_unreviewed":
            return "AI · 未审核 · 词库外参考"
        return "词库外参考"


@dataclass(frozen=True, slots=True)
class WordLookupItem:
    """Small local-bank result used by the bounded vocabulary search page."""

    word_id: int
    word: str
    phonetic: str
    meaning: str
    level: str

    @property
    def reference(self) -> LinkedWordReference:
        return LinkedWordReference(
            word=self.word,
            meaning=self.meaning,
            trust="source_validated",
        )


class WordDetailService:
    """Load an existing word or a safe, non-persistent reference fallback."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def search_words(
        self,
        query: str,
        limit: int = 50,
    ) -> list[WordLookupItem]:
        """Search the bundled bank by exact headword first, then prefix."""
        normalized = _normalize_search_term(query)
        if not normalized:
            return []
        safe_limit = max(1, min(int(limit), 100))
        exact_rank = case((func.lower(Word.word) == normalized, 0), else_=1)
        with self.database.session() as session:
            words = session.scalars(
                select(Word)
                .where(func.lower(Word.word).like(f"{normalized}%"))
                .order_by(exact_rank, Word.word.asc())
                .limit(safe_limit)
            ).all()
            return [
                WordLookupItem(
                    word_id=word.id,
                    word=word.word,
                    phonetic=word.phonetic,
                    meaning=word.meaning,
                    level=word.level.value,
                )
                for word in words
            ]

    def get_word_detail(self, reference: LinkedWordReference) -> WordDetailView:
        """Return a detail projection without writes, scheduling, or model calls."""
        normalized = _normalize_headword(reference.word)
        with self.database.session() as session:
            word = session.scalar(
                select(Word).where(func.lower(Word.word) == normalized)
            )
            if word is None:
                return _reference_only_view(
                    LinkedWordReference(
                        word=reference.word.strip(),
                        part_of_speech=reference.part_of_speech,
                        meaning=reference.meaning,
                        english_definition=reference.english_definition,
                        trust=reference.trust,
                    )
                )

            aid = session.scalar(
                select(WordLearningAid).where(WordLearningAid.word_id == word.id)
            )
            fact = session.scalar(
                select(WordLexicalFact).where(WordLexicalFact.word_id == word.id)
            )
            feedback_reported = (
                session.scalar(
                    select(WordLearningAidFeedback.word_id).where(
                        WordLearningAidFeedback.word_id == word.id
                    )
                )
                is not None
            )
            facts = build_lexical_facts_view(
                fact,
                aid,
                feedback_reported=feedback_reported,
            )
            canonical_reference = LinkedWordReference(
                word=word.word,
                part_of_speech=reference.part_of_speech,
                meaning=word.meaning,
                english_definition=reference.english_definition,
                trust=reference.trust,
            )
            return WordDetailView(
                reference=canonical_reference,
                word=word.word,
                phonetic=word.phonetic,
                meaning=word.meaning,
                level=word.level.value,
                example=resolve_example(word.example, aid),
                example_translation=resolve_example_translation(aid),
                sections=facts.sections,
            )


def _reference_only_view(reference: LinkedWordReference) -> WordDetailView:
    meaning = reference.meaning.strip()
    if reference.part_of_speech and meaning:
        meaning = f"{reference.part_of_speech} {meaning}"
    elif reference.part_of_speech:
        meaning = reference.part_of_speech
    return WordDetailView(
        reference=reference,
        word=reference.word.strip(),
        phonetic="",
        meaning=meaning,
        level="词库外",
        example="",
        example_translation="",
        sections=(),
        reference_only=True,
    )


def _normalize_headword(value: str) -> str:
    word = str(value or "").strip()
    if not word or len(word) > 100 or not _HEADWORD_PATTERN.fullmatch(word):
        raise ValueError("关联词不是受支持的单词格式")
    return word.casefold()


def _normalize_search_term(value: str) -> str:
    term = " ".join(str(value or "").split()).casefold()
    if not term or not _SEARCH_PATTERN.fullmatch(term):
        return ""
    return term
