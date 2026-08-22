"""Pure, deterministic policy for proactive review reminders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.utils.datetime_utils import ensure_utc


@dataclass(frozen=True, slots=True)
class ReminderContext:
    current_time: datetime
    due_word_count: int
    last_notification_time: datetime | None = None
    last_snooze_time: datetime | None = None
    today_completed: bool = False
    review_session_active: bool = False


@dataclass(frozen=True, slots=True)
class ReminderDecision:
    should_notify: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ReminderPolicy:
    start_time: time = time(8, 0)
    end_time: time = time(23, 0)
    cooldown: timedelta = timedelta(minutes=30)

    def evaluate(self, context: ReminderContext) -> ReminderDecision:
        now = ensure_utc(context.current_time)
        local_time = now.astimezone().time().replace(tzinfo=None)
        if context.due_word_count <= 0:
            return ReminderDecision(False, "no_due_words")
        if context.review_session_active:
            return ReminderDecision(False, "review_session_active")
        if context.today_completed:
            return ReminderDecision(False, "today_completed")
        if local_time < self.start_time or local_time >= self.end_time:
            return ReminderDecision(False, "quiet_hours")
        if self._inside_cooldown(now, context.last_snooze_time):
            return ReminderDecision(False, "snoozed")
        if self._inside_cooldown(now, context.last_notification_time):
            return ReminderDecision(False, "notification_cooldown")
        return ReminderDecision(True, "due_words_available")

    def _inside_cooldown(self, now: datetime, previous: datetime | None) -> bool:
        if previous is None:
            return False
        elapsed = now - ensure_utc(previous)
        if elapsed < timedelta(0):
            # Small clock corrections should retain the cooldown, while a
            # corrupt or far-future timestamp must not suppress reminders for
            # hours or days after the system clock is restored.
            return -elapsed < self.cooldown
        return elapsed < self.cooldown
