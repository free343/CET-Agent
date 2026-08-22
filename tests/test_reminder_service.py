from __future__ import annotations

from datetime import datetime, timedelta

from app.services.reminder_service import ReminderService
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_snooze_survives_service_restart(database, word_id) -> None:
    review_service = ReviewService(database)
    first = ReminderService(review_service, clock=lambda: NOW)
    first.snooze(NOW)

    restarted = ReminderService(review_service, clock=lambda: NOW)
    status = restarted.evaluate(NOW + timedelta(minutes=10))

    assert restarted.last_snooze_time == NOW
    assert status.decision.should_notify is False
    assert status.decision.reason == "snoozed"


def test_new_due_word_clears_completed_state(database, word_id) -> None:
    review_service = ReviewService(database)
    service = ReminderService(review_service, clock=lambda: NOW)
    service.mark_today_completed()

    status = service.evaluate(NOW)

    assert service.today_completed is False
    assert status.decision.should_notify is True
