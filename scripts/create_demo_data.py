"""Create repeatable correlated-error history and rebuild the graph."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.bootstrap import initialize_database
from app.db.models import LearningState, ReviewLog, Word
from app.services.analysis_service import AnalysisService
from app.utils.datetime_utils import utc_now

GROUPS = (
    ("adapt", "adopt", "adept"),
    ("economic", "economical"),
    ("complement", "compliment"),
)


def create_demo_data() -> None:
    database = initialize_database()
    try:
        with database.session() as session:
            existing_demo = int(
                session.scalar(
                    select(func.count(ReviewLog.id)).where(
                        ReviewLog.question_type == "demo_confusion"
                    )
                )
                or 0
            )
            if existing_demo == 0:
                all_words = {word.word: word for word in session.scalars(select(Word))}
                now = utc_now()
                for group_index, group in enumerate(GROUPS):
                    for word_text in group:
                        word = all_words[word_text]
                        state = session.scalar(
                            select(LearningState).where(
                                LearningState.word_id == word.id
                            )
                        )
                        for occurrence in range(4):
                            reviewed_at = now - timedelta(
                                days=occurrence * 4 + group_index,
                                hours=2,
                            )
                            session.add(
                                ReviewLog(
                                    word_id=word.id,
                                    reviewed_at=reviewed_at,
                                    rating=1,
                                    is_correct=False,
                                    response_time_ms=1800 + occurrence * 120,
                                    question_type="demo_confusion",
                                    user_answer="",
                                    previous_stability=1.5,
                                    new_stability=0.5,
                                    previous_difficulty=5.0,
                                    new_difficulty=5.9,
                                    scheduled_days=10 / (24 * 60),
                                )
                            )
                        if state is not None:
                            state.review_count += 4
                            state.error_count += 4
                            state.lapse_count += 4
        result = AnalysisService(database).rebuild_confusion_graph()
        print(
            f"Demo ready: candidates={result.candidate_count}, "
            f"edges={result.edge_count}, clusters={result.cluster_count}"
        )
        for cluster in AnalysisService(database).get_clusters():
            print(
                f"Cluster #{cluster.cluster_number}: {', '.join(cluster.words)} "
                f"({cluster.average_score:.2f})"
            )
    finally:
        database.dispose()


if __name__ == "__main__":
    create_demo_data()
