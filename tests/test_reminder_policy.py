from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.reminder_policy import ReminderContext, ReminderPolicy

POLICY = ReminderPolicy(cooldown=timedelta(minutes=30))
LOCAL_ZONE = datetime.now().astimezone().tzinfo
NOON = datetime(2026, 8, 21, 12, tzinfo=LOCAL_ZONE)


def test_no_reminder_during_quiet_hours() -> None:
    local_midnight = datetime(2026, 8, 21, 2, 0, tzinfo=LOCAL_ZONE)
    decision = POLICY.evaluate(ReminderContext(local_midnight, 5))
    assert decision.should_notify is False
    assert decision.reason == "quiet_hours"


def test_no_reminder_during_review_session() -> None:
    decision = POLICY.evaluate(ReminderContext(NOON, 5, review_session_active=True))
    assert decision.should_notify is False
    assert decision.reason == "review_session_active"


def test_no_reminder_inside_snooze_window() -> None:
    decision = POLICY.evaluate(
        ReminderContext(NOON, 5, last_snooze_time=NOON - timedelta(minutes=10))
    )
    assert decision.should_notify is False
    assert decision.reason == "snoozed"


def test_due_words_trigger_reminder() -> None:
    decision = POLICY.evaluate(ReminderContext(NOON, 17))
    assert decision.should_notify is True
    assert decision.reason == "due_words_available"


def test_far_future_cooldown_timestamp_does_not_suppress_indefinitely() -> None:
    decision = POLICY.evaluate(
        ReminderContext(
            NOON,
            5,
            last_notification_time=NOON + timedelta(days=1),
        )
    )
    assert decision.should_notify is True
    assert decision.reason == "due_words_available"
