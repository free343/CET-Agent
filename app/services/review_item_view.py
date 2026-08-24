"""Read-only projection from persisted card state to bounded UI review items."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    FavoriteWord,
    LearningAidIssueType,
    LearningState,
    MasteredWord,
    Word,
    WordAcquisitionState,
    WordLearningAid,
    WordLearningAidFeedback,
    WordLevel,
    WordLexicalFact,
)
from app.domain.acquisition import (
    EnglishCandidate,
    EnglishOption,
    build_cloze_question,
)
from app.domain.meaning_quiz import (
    MeaningCandidate,
    MeaningOption,
    build_meaning_options,
)
from app.services.learning_aid_view import (
    format_collocations,
    format_word_family,
    resolve_example,
    resolve_example_translation,
)
from app.services.lexical_fact_view import (
    LexicalFactSection,
    build_lexical_facts_view,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewItem:
    word_id: int
    word: str
    phonetic: str
    meaning: str
    example: str
    level: WordLevel
    lapse_count: int
    error_count: int
    next_review_at: datetime
    proficiency_level: int = 3
    meaning_options: tuple[MeaningOption, ...] = ()
    cloze_example: str = ""
    cloze_options: tuple[EnglishOption, ...] = ()
    is_favorite: bool = False
    is_mastered: bool = False
    example_translation: str = ""
    collocations: tuple[str, ...] = ()
    word_family: tuple[str, ...] = ()
    has_learning_aid: bool = False
    learning_aid_feedback: LearningAidIssueType | None = None
    lexical_sections: tuple[LexicalFactSection, ...] = ()
    lexical_facts_available: bool = False


def build_review_items(
    session: Session,
    states: list[LearningState],
) -> list[ReviewItem]:
    if not states:
        return []
    word_ids = [state.word_id for state in states]
    favorite_ids = set(
        session.scalars(
            select(FavoriteWord.word_id).where(FavoriteWord.word_id.in_(word_ids))
        )
    )
    mastered_ids = set(
        session.scalars(
            select(MasteredWord.word_id).where(MasteredWord.word_id.in_(word_ids))
        )
    )
    acquisition_levels = dict(
        session.execute(
            select(
                WordAcquisitionState.word_id,
                WordAcquisitionState.proficiency_level,
            ).where(WordAcquisitionState.word_id.in_(word_ids))
        )
        .tuples()
        .all()
    )
    aid_by_word_id = {
        aid.word_id: aid
        for aid in session.scalars(
            select(WordLearningAid).where(WordLearningAid.word_id.in_(word_ids))
        )
    }
    feedback_by_word_id = {
        feedback.word_id: feedback.issue_type
        for feedback in session.scalars(
            select(WordLearningAidFeedback).where(
                WordLearningAidFeedback.word_id.in_(word_ids)
            )
        )
    }
    lexical_fact_by_word_id = {
        fact.word_id: fact
        for fact in session.scalars(
            select(WordLexicalFact).where(WordLexicalFact.word_id.in_(word_ids))
        )
    }
    lexical_facts_available = (
        session.scalar(select(WordLexicalFact.word_id).limit(1)) is not None
    )
    candidates_by_level = _meaning_candidates_by_level(session, states)
    english_candidates_by_level = _english_candidates_by_level(session, states)
    results: list[ReviewItem] = []
    for state in states:
        proficiency_level = acquisition_levels.get(
            state.word.id,
            3 if state.review_count > 0 or state.last_review_at is not None else 0,
        )
        example = resolve_example(
            state.word.example,
            aid_by_word_id.get(state.word.id),
        )
        cloze = None
        if proficiency_level == 1:
            cloze = build_cloze_question(
                EnglishCandidate(
                    word_id=state.word.id,
                    word=state.word.word,
                    meaning=state.word.meaning,
                    frequency=state.word.frequency,
                ),
                example,
                english_candidates_by_level.get(state.word.level, []),
            )
            if cloze is None:
                logger.error(
                    "Unable to build deterministic acquisition cloze "
                    "word_id=%s word=%s example=%r candidate_count=%s",
                    state.word.id,
                    state.word.word,
                    example,
                    len(english_candidates_by_level.get(state.word.level, [])),
                )
        meaning_options = build_meaning_options(
            MeaningCandidate(
                word_id=state.word.id,
                meaning=state.word.meaning,
                frequency=state.word.frequency,
                review_count=state.review_count,
            ),
            candidates_by_level.get(state.word.level, []),
        )
        if proficiency_level == 0 and len(meaning_options) != 4:
            logger.error(
                "Unable to build deterministic acquisition meaning choices "
                "word_id=%s word=%s option_count=%s candidate_count=%s",
                state.word.id,
                state.word.word,
                len(meaning_options),
                len(candidates_by_level.get(state.word.level, [])),
            )
        results.append(
            ReviewItem(
                word_id=state.word.id,
                word=state.word.word,
                phonetic=state.word.phonetic,
                meaning=state.word.meaning,
                example=example,
                level=state.word.level,
                lapse_count=state.lapse_count,
                error_count=state.error_count,
                next_review_at=state.next_review_at,
                proficiency_level=proficiency_level,
                meaning_options=meaning_options,
                cloze_example=cloze.text if cloze is not None else "",
                cloze_options=cloze.options if cloze is not None else (),
                is_favorite=state.word.id in favorite_ids,
                is_mastered=state.word.id in mastered_ids,
                example_translation=resolve_example_translation(
                    aid_by_word_id.get(state.word.id)
                ),
                collocations=format_collocations(aid_by_word_id.get(state.word.id)),
                word_family=format_word_family(aid_by_word_id.get(state.word.id)),
                has_learning_aid=state.word.id in aid_by_word_id,
                learning_aid_feedback=feedback_by_word_id.get(state.word.id),
                lexical_sections=build_lexical_facts_view(
                    lexical_fact_by_word_id.get(state.word.id),
                    aid_by_word_id.get(state.word.id),
                    feedback_reported=(
                        feedback_by_word_id.get(state.word.id) is not None
                    ),
                    origin_word=state.word.word,
                    origin_meaning=state.word.meaning,
                ).sections,
                lexical_facts_available=lexical_facts_available,
            )
        )
    return results


def _meaning_candidates_by_level(
    session: Session,
    states: list[LearningState],
) -> dict[WordLevel, list[MeaningCandidate]]:
    levels = {state.word.level for state in states}
    if not levels:
        return {}
    candidates_by_level: dict[WordLevel, list[MeaningCandidate]] = {
        level: [] for level in levels
    }
    rows = session.execute(
        select(
            Word.id,
            Word.meaning,
            Word.frequency,
            Word.level,
            LearningState.review_count,
        )
        .join(LearningState, LearningState.word_id == Word.id)
        .where(Word.level.in_(levels))
    ).all()
    for row in rows:
        candidates_by_level[row.level].append(
            MeaningCandidate(
                word_id=row.id,
                meaning=row.meaning,
                frequency=row.frequency,
                review_count=row.review_count,
            )
        )
    return candidates_by_level


def _english_candidates_by_level(
    session: Session,
    states: list[LearningState],
) -> dict[WordLevel, list[EnglishCandidate]]:
    levels = {state.word.level for state in states}
    candidates_by_level: dict[WordLevel, list[EnglishCandidate]] = {
        level: [] for level in levels
    }
    if not levels:
        return candidates_by_level
    rows = session.execute(
        select(
            Word.id,
            Word.word,
            Word.meaning,
            Word.frequency,
            Word.level,
        ).where(Word.level.in_(levels))
    ).all()
    for row in rows:
        candidates_by_level[row.level].append(
            EnglishCandidate(
                word_id=row.id,
                word=row.word,
                meaning=row.meaning,
                frequency=row.frequency,
            )
        )
    return candidates_by_level
