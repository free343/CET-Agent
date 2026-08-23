from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.db.models import (
    LearningAidIssueType,
    WordLearningAid,
    WordLearningAidFeedback,
)
from app.services.learning_aid_feedback_service import LearningAidFeedbackService
from app.services.review_service import ReviewService


def _add_aid(database, word_id: int) -> None:
    with database.session() as session:
        session.add(
            WordLearningAid(
                word_id=word_id,
                collocations_json=json.dumps(
                    [{"phrase": "adapt to", "meaning": "适应"}],
                    ensure_ascii=False,
                ),
                word_family_json="[]",
                content_status="ai_generated_unreviewed",
                content_hash="feedback-test",
            )
        )


def test_learning_aid_feedback_is_idempotently_persisted(database, word_id) -> None:
    _add_aid(database, word_id)
    service = LearningAidFeedbackService(database)

    first = service.report_issue(word_id, LearningAidIssueType.EXAMPLE_UNNATURAL)
    second = service.report_issue(
        word_id,
        LearningAidIssueType.WORD_FAMILY_INCORRECT,
    )

    assert first.issue_type is LearningAidIssueType.EXAMPLE_UNNATURAL
    assert second.issue_type is LearningAidIssueType.WORD_FAMILY_INCORRECT
    with database.session() as session:
        rows = session.scalars(select(WordLearningAidFeedback)).all()
        assert len(rows) == 1
        assert rows[0].word_id == word_id
        assert rows[0].issue_type is LearningAidIssueType.WORD_FAMILY_INCORRECT
        assert rows[0].updated_at >= rows[0].created_at


def test_learning_aid_feedback_rejects_word_without_aid(database, word_id) -> None:
    with pytest.raises(LookupError, match="learning aid"):
        LearningAidFeedbackService(database).report_issue(
            word_id,
            LearningAidIssueType.OTHER,
        )


def test_review_item_exposes_existing_learning_aid_feedback(database, word_id) -> None:
    _add_aid(database, word_id)
    LearningAidFeedbackService(database).report_issue(
        word_id,
        LearningAidIssueType.TRANSLATION_INACCURATE,
    )

    item = ReviewService(database).get_due_words()[0]

    assert item.has_learning_aid is True
    assert item.learning_aid_feedback is LearningAidIssueType.TRANSLATION_INACCURATE
