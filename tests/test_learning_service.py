from __future__ import annotations

from datetime import datetime, timedelta

from app.db.models import LearningState, Word, WordLevel
from app.domain.fsrs_scheduler import Rating
from app.services.learning_service import LearningService
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_dashboard_statistics_are_derived_from_review_logs(database, word_id) -> None:
    with database.session() as session:
        second = Word(word="adopt", meaning="采用", level=WordLevel.CET4)
        second.learning_state = LearningState(next_review_at=NOW)
        session.add(second)
        session.flush()
        second_id = second.id

    reviews = ReviewService(database)
    reviews.submit_review(word_id, Rating.AGAIN, 1200, reviewed_at=NOW)
    reviews.submit_review(second_id, Rating.GOOD, 900, reviewed_at=NOW)

    stats = LearningService(database).dashboard_stats(NOW)

    assert stats.today_completed == 2
    assert stats.seven_day_accuracy == 50.0
    assert stats.learning_streak == 1
    assert stats.high_frequency_wrong[0].word == "adapt"
    assert stats.high_frequency_wrong[0].error_count == 1


def test_dashboard_ignores_future_review_logs(database, word_id) -> None:
    ReviewService(database).submit_review(
        word_id,
        Rating.GOOD,
        900,
        reviewed_at=NOW.replace(year=NOW.year + 1),
    )

    stats = LearningService(database).dashboard_stats(NOW)

    assert stats.today_completed == 0
    assert stats.seven_day_accuracy == 0.0
    assert stats.learning_streak == 0
    assert stats.high_frequency_wrong == ()
    assert stats.future_review_count == 1
    assert stats.latest_future_review_at == NOW.replace(year=NOW.year + 1)


def test_dashboard_is_filtered_by_study_level(database, word_id) -> None:
    with database.session() as session:
        cet6_word = Word(word="adept", meaning="熟练的", level=WordLevel.CET6)
        cet6_word.learning_state = LearningState(next_review_at=NOW)
        session.add(cet6_word)

    cet4 = LearningService(database, WordLevel.CET4).dashboard_stats(NOW)
    cet6 = LearningService(database, WordLevel.CET6).dashboard_stats(NOW)
    combined = LearningService(database).dashboard_stats(NOW)

    assert cet4.new_count == 1
    assert cet6.new_count == 1
    assert combined.new_count == 2
    assert cet4.due_count == 0
    assert cet6.due_count == 0
    assert combined.due_count == 0


def test_dashboard_splits_new_words_from_due_reviews(database, word_id) -> None:
    with database.session() as session:
        learned = Word(word="reviewdue", meaning="到期词", level=WordLevel.CET4)
        learned.learning_state = LearningState(
            next_review_at=NOW - timedelta(hours=1),
            last_review_at=NOW - timedelta(days=2),
            review_count=1,
            fsrs_state=2,
            fsrs_step=None,
        )
        session.add(learned)

    stats = LearningService(database, WordLevel.CET4).dashboard_stats(NOW)

    assert stats.new_count == 1
    assert stats.due_count == 1
