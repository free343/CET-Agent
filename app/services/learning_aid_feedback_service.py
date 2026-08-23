"""Persistent local quality feedback for generated word learning aids."""

from __future__ import annotations

from dataclasses import dataclass

from app.db.database import Database
from app.db.models import (
    LearningAidIssueType,
    WordLearningAid,
    WordLearningAidFeedback,
)
from app.utils.datetime_utils import utc_now


@dataclass(frozen=True, slots=True)
class LearningAidFeedbackUpdate:
    word_id: int
    issue_type: LearningAidIssueType


class LearningAidFeedbackService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def report_issue(
        self,
        word_id: int,
        issue_type: LearningAidIssueType | str,
    ) -> LearningAidFeedbackUpdate:
        selected_issue = LearningAidIssueType(issue_type)
        reported_at = utc_now()
        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            if session.get(WordLearningAid, word_id) is None:
                raise LookupError(f"No learning aid for word_id={word_id}")
            feedback = session.get(WordLearningAidFeedback, word_id)
            if feedback is None:
                session.add(
                    WordLearningAidFeedback(
                        word_id=word_id,
                        issue_type=selected_issue,
                        created_at=reported_at,
                        updated_at=reported_at,
                    )
                )
            else:
                feedback.issue_type = selected_issue
                feedback.updated_at = reported_at
        return LearningAidFeedbackUpdate(
            word_id=word_id,
            issue_type=selected_issue,
        )
