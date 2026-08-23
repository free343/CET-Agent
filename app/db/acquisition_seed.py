"""Idempotent adoption of durable pre-FSRS acquisition state."""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import LearningState, ReviewLog, Word, WordAcquisitionState


def ensure_acquisition_states(session: Session) -> int:
    """Create missing states while preserving all existing review history.

    A word with any real review evidence is already acquired. Demo-only graph
    evidence does not count as learning and therefore adopts proficiency 0.
    """

    latest_real_review = func.max(
        case(
            (ReviewLog.question_type != "demo_confusion", ReviewLog.reviewed_at),
            else_=None,
        )
    )
    rows = session.execute(
        select(
            Word.id,
            LearningState.review_count,
            LearningState.last_review_at,
            latest_real_review.label("latest_real_review"),
        )
        .outerjoin(LearningState, LearningState.word_id == Word.id)
        .outerjoin(ReviewLog, ReviewLog.word_id == Word.id)
        .outerjoin(WordAcquisitionState, WordAcquisitionState.word_id == Word.id)
        .where(WordAcquisitionState.word_id.is_(None))
        .group_by(
            Word.id,
            LearningState.review_count,
            LearningState.last_review_at,
        )
    ).all()
    for row in rows:
        acquired = bool((row.review_count or 0) > 0 or row.latest_real_review)
        session.add(
            WordAcquisitionState(
                word_id=row.id,
                proficiency_level=3 if acquired else 0,
                completed_at=(
                    row.last_review_at or row.latest_real_review if acquired else None
                ),
            )
        )
    session.flush()
    return len(rows)
