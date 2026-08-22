"""Stateful reminder coordination around the pure reminder policy."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import Settings, settings
from app.db.models import ReminderRuntimeState
from app.domain.reminder_policy import ReminderContext, ReminderDecision, ReminderPolicy
from app.services.review_service import ReviewService
from app.utils.datetime_utils import ensure_utc, utc_now


@dataclass(frozen=True, slots=True)
class ReminderStatus:
    decision: ReminderDecision
    due_word_count: int
    estimated_minutes: int


class ReminderService:
    def __init__(
        self,
        review_service: ReviewService,
        app_settings: Settings = settings,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.review_service = review_service
        self._clock = clock
        self.policy = ReminderPolicy(
            start_time=app_settings.reminder_start_time,
            end_time=app_settings.reminder_end_time,
            cooldown=timedelta(minutes=app_settings.reminder_cooldown_minutes),
        )
        self.last_notification_time: datetime | None = None
        self.last_snooze_time: datetime | None = None
        self.today_completed = False
        self.review_session_active = False
        self._state_date = ensure_utc(self._clock()).astimezone().date()
        self._load_persisted_state()

    def evaluate(self, now: datetime | None = None) -> ReminderStatus:
        checked_at = ensure_utc(now or self._clock())
        self._reset_for_new_day(checked_at)
        due_count = self.review_service.due_count(checked_at)
        if due_count > 0 and self.today_completed:
            # A card may become due again later on the same day. In that case
            # the previously completed daily state is no longer true.
            self.today_completed = False
            self._save_persisted_state()
        decision = self.policy.evaluate(
            ReminderContext(
                current_time=checked_at,
                due_word_count=due_count,
                last_notification_time=self.last_notification_time,
                last_snooze_time=self.last_snooze_time,
                today_completed=self.today_completed,
                review_session_active=self.review_session_active,
            )
        )
        return ReminderStatus(
            decision=decision,
            due_word_count=due_count,
            estimated_minutes=max(1, math.ceil(due_count / 4)) if due_count else 0,
        )

    def notification_sent(self, now: datetime | None = None) -> None:
        self.last_notification_time = ensure_utc(now or self._clock())
        self._save_persisted_state()

    def snooze(self, now: datetime | None = None) -> None:
        self.last_snooze_time = ensure_utc(now or self._clock())
        self._save_persisted_state()

    def set_review_session_active(self, active: bool) -> None:
        self.review_session_active = active

    def mark_today_completed(self) -> None:
        self.today_completed = True
        self._save_persisted_state()

    def remaining_due_count(self, now: datetime | None = None) -> int:
        return self.review_service.due_count(ensure_utc(now or self._clock()))

    def _reset_for_new_day(self, now: datetime) -> None:
        local_date = now.astimezone().date()
        if local_date != self._state_date:
            self._state_date = local_date
            self.today_completed = False
            self.last_snooze_time = None
            self._save_persisted_state()

    def _load_persisted_state(self) -> None:
        with self.review_service.database.session() as session:
            state = session.scalar(
                select(ReminderRuntimeState).where(ReminderRuntimeState.id == 1)
            )
            if state is None:
                session.add(ReminderRuntimeState(id=1))
                return
            self.last_notification_time = state.last_notification_at
            self.last_snooze_time = state.last_snooze_at
            self.today_completed = (
                state.completed_local_date == self._state_date.isoformat()
            )

    def _save_persisted_state(self) -> None:
        with self.review_service.database.session() as session:
            state = session.get(ReminderRuntimeState, 1)
            if state is None:
                state = ReminderRuntimeState(id=1)
                session.add(state)
            state.last_notification_at = self.last_notification_time
            state.last_snooze_at = self.last_snooze_time
            state.completed_local_date = (
                self._state_date.isoformat() if self.today_completed else None
            )
