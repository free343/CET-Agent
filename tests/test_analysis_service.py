from __future__ import annotations

from datetime import datetime, timedelta

from app.config import Settings
from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.services.analysis_service import AnalysisService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def _error_log(word_id: int, reviewed_at: datetime) -> ReviewLog:
    return ReviewLog(
        word_id=word_id,
        reviewed_at=reviewed_at,
        rating=1,
        is_correct=False,
        response_time_ms=1000,
        question_type="analysis_test",
        user_answer="",
        previous_stability=1.0,
        new_stability=0.4,
        previous_difficulty=5.0,
        new_difficulty=5.9,
        scheduled_days=10 / (24 * 60),
    )


def test_analysis_uses_same_window_for_cluster_error_counts(database) -> None:
    with database.session() as session:
        words = []
        for text in ("adapt", "adopt"):
            word = Word(word=text, meaning=text, level=WordLevel.CET4)
            word.learning_state = LearningState(next_review_at=NOW)
            session.add(word)
            session.flush()
            words.append(word)
        for occurrence in range(2):
            reviewed_at = NOW - timedelta(days=occurrence * 2)
            session.add(_error_log(words[0].id, reviewed_at))
            session.add(_error_log(words[1].id, reviewed_at))
        session.add(_error_log(words[0].id, NOW - timedelta(days=45)))

    service = AnalysisService(
        database,
        app_settings=Settings(confusion_threshold=0.65),
    )
    result = service.rebuild_confusion_graph(NOW)
    clusters = service.get_clusters(NOW)

    assert result.edge_count == 1
    assert len(clusters) == 1
    assert clusters[0].error_counts == (2, 2)


def test_analysis_ignores_future_review_logs(database) -> None:
    with database.session() as session:
        words = []
        for text in ("adapt", "adopt"):
            word = Word(word=text, meaning=text, level=WordLevel.CET4)
            word.learning_state = LearningState(next_review_at=NOW)
            session.add(word)
            session.flush()
            words.append(word)
        for occurrence in range(2):
            reviewed_at = NOW + timedelta(days=occurrence + 1)
            session.add(_error_log(words[0].id, reviewed_at))
            session.add(_error_log(words[1].id, reviewed_at))

    service = AnalysisService(
        database,
        app_settings=Settings(confusion_threshold=0.65),
    )
    result = service.rebuild_confusion_graph(NOW)

    assert result.candidate_count == 0
    assert result.edge_count == 0
    assert result.cluster_count == 0
