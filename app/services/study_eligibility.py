"""Shared SQL predicates for acquisition, review, practice, and mastery."""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import LearningState, MasteredWord, WordAcquisitionState


def effective_proficiency() -> ColumnElement[int]:
    """Use durable state, with a safe compatibility fallback for old fixtures."""

    persisted_level = (
        select(WordAcquisitionState.proficiency_level)
        .where(WordAcquisitionState.word_id == LearningState.word_id)
        .scalar_subquery()
    )
    return func.coalesce(
        persisted_level,
        case(
            (
                (LearningState.review_count > 0)
                | LearningState.last_review_at.is_not(None),
                3,
            ),
            else_=0,
        ),
    )


def is_not_mastered() -> ColumnElement[bool]:
    mastered = (
        select(MasteredWord.word_id)
        .where(MasteredWord.word_id == LearningState.word_id)
        .exists()
    )
    return ~mastered
