from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

from sqlalchemy import func, select

from app.db.models import ReminderReviewLease, ReminderRuntimeState
from app.services.reminder_service import (
    REVIEW_SESSION_LEASE_DURATION,
    ReminderService,
)
from app.services.review_service import ReviewService
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_snooze_survives_service_restart(database, word_id) -> None:
    review_service = ReviewService(database)
    first = ReminderService(review_service, clock=lambda: NOW)
    wake_at = first.snooze(NOW)

    restarted = ReminderService(review_service, clock=lambda: NOW)
    status = restarted.evaluate(NOW + timedelta(minutes=10))

    assert restarted.last_snooze_time == NOW
    assert status.decision.should_notify is False
    assert status.decision.reason == "snoozed"
    assert wake_at == NOW + timedelta(minutes=30)
    assert status.next_evaluation_at == wake_at


def test_notification_claim_schedules_exact_cooldown_recheck(
    database,
    word_id,
) -> None:
    service = ReminderService(ReviewService(database), clock=lambda: NOW)

    claimed = service.evaluate_and_claim(NOW)
    suppressed = service.evaluate(NOW + timedelta(minutes=10))

    expected = NOW + timedelta(minutes=30)
    assert claimed.decision.should_notify is True
    assert claimed.next_evaluation_at == expected
    assert suppressed.decision.reason == "notification_cooldown"
    assert suppressed.next_evaluation_at == expected


def test_new_due_word_clears_completed_state(database, word_id) -> None:
    review_service = ReviewService(database)
    service = ReminderService(review_service, clock=lambda: NOW)
    service.mark_today_completed()

    status = service.evaluate(NOW)

    assert service.today_completed is False
    assert status.decision.should_notify is True


def test_snooze_is_cleared_on_the_next_local_day(database, word_id) -> None:
    service = ReminderService(ReviewService(database), clock=lambda: NOW)
    service.snooze(NOW)

    status = service.evaluate(NOW + timedelta(days=1))

    assert service.last_snooze_time is None
    assert status.decision.should_notify is True


def test_concurrent_services_atomically_claim_one_notification(
    database,
    word_id,
) -> None:
    services = [
        ReminderService(ReviewService(database), clock=lambda: NOW) for _ in range(2)
    ]
    barrier = Barrier(2)

    def claim(service: ReminderService):
        barrier.wait(timeout=2)
        return service.evaluate_and_claim(NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(claim, services))

    assert sum(status.decision.should_notify for status in statuses) == 1
    assert {status.decision.reason for status in statuses} == {
        "due_words_available",
        "notification_cooldown",
    }
    with database.session() as session:
        state = session.get(ReminderRuntimeState, 1)
        assert state is not None
        assert state.last_notification_at == NOW


def test_other_instance_review_lease_suppresses_notification(
    database,
    word_id,
) -> None:
    active = ReminderService(
        ReviewService(database),
        clock=lambda: NOW,
        instance_id="active-window",
    )
    observer = ReminderService(
        ReviewService(database),
        clock=lambda: NOW,
        instance_id="observer-window",
    )
    active.publish_review_session(True, NOW)

    suppressed = observer.evaluate_and_claim(NOW)

    assert suppressed.decision.should_notify is False
    assert suppressed.decision.reason == "review_session_active"
    active.publish_review_session(False, NOW)
    available = observer.evaluate_and_claim(NOW)
    assert available.decision.should_notify is True


def test_review_leases_are_per_instance_and_expire(database, word_id) -> None:
    services = [
        ReminderService(
            ReviewService(database),
            clock=lambda: NOW,
            instance_id=instance_id,
        )
        for instance_id in ("window-a", "window-b", "observer")
    ]
    first, second, observer = services
    first.publish_review_session(True, NOW)
    second.publish_review_session(True, NOW)
    first.publish_review_session(False, NOW)

    assert observer.evaluate(NOW).decision.reason == "review_session_active"
    with database.session() as session:
        assert session.scalar(select(func.count(ReminderReviewLease.owner_id))) == 1

    expired_at = NOW + REVIEW_SESSION_LEASE_DURATION + timedelta(seconds=1)
    status = observer.evaluate(expired_at)

    assert status.decision.should_notify is True
    with database.session() as session:
        assert session.scalar(select(func.count(ReminderReviewLease.owner_id))) == 0
