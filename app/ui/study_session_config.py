"""Shared immutable configuration for study-page session variants."""

from __future__ import annotations

from enum import Enum

from app.db.models import LearningAidIssueType
from app.services.practice_service import PracticeScope


class StudySessionMode(str, Enum):
    """The explicit learning intent behind a shared card workflow."""

    COMBINED = "COMBINED"
    LEARN = "LEARN"
    REVIEW = "REVIEW"
    PRACTICE = "PRACTICE"


PRACTICE_SCOPE_LABELS: tuple[tuple[str, PracticeScope], ...] = (
    ("昨天学过", PracticeScope.YESTERDAY),
    ("最近学习", PracticeScope.RECENT),
    ("历史错词", PracticeScope.WRONG),
    ("收藏单词", PracticeScope.FAVORITES),
)


LEARNING_AID_ISSUE_CHOICES: tuple[tuple[str, LearningAidIssueType], ...] = (
    ("例句不自然", LearningAidIssueType.EXAMPLE_UNNATURAL),
    ("例句与释义不匹配", LearningAidIssueType.MEANING_MISMATCH),
    ("中文翻译不准确", LearningAidIssueType.TRANSLATION_INACCURATE),
    ("固定搭配不常用", LearningAidIssueType.COLLOCATION_UNCOMMON),
    ("同族或派生词关系错误", LearningAidIssueType.WORD_FAMILY_INCORRECT),
    ("其他问题", LearningAidIssueType.OTHER),
)


RATING_SHORTCUT_GUARD_SECONDS = 0.45
