"""Stateful reminder coordination around the pure reminder policy."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Lock
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.db.models import ReminderReviewLease, ReminderRuntimeState
from app.domain.reminder_policy import ReminderContext, ReminderDecision, ReminderPolicy
from app.services.review_service import ReviewService
from app.utils.datetime_utils import ensure_utc, utc_now

REVIEW_SESSION_LEASE_DURATION = timedelta(minutes=10)


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
        instance_id: str | None = None,
    ) -> None:
        self.review_service = review_service
        self._clock = clock
        self.policy = ReminderPolicy(
            start_time=app_settings.reminder_start_time,
            end_time=app_settings.reminder_end_time,
            cooldown=timedelta(minutes=app_settings.reminder_cooldown_minutes),
        )
        self.instance_id = (instance_id or uuid4().hex).strip()
        if not self.instance_id or len(self.instance_id) > 64:
            raise ValueError("Reminder instance_id must contain 1 to 64 characters")
        self.last_notification_time: datetime | None = None
        self.last_snooze_time: datetime | None = None
        self.today_completed = False
        self.review_session_active = False
        self._session_state_lock = Lock()
        self._state_date = ensure_utc(self._clock()).astimezone().date()
        self._load_persisted_state()

    def evaluate(self, now: datetime | None = None) -> ReminderStatus:
        return self._evaluate(now, claim_notification=False)

    def evaluate_and_claim(self, now: datetime | None = None) -> ReminderStatus:
        """Atomically claim a notification slot when the policy allows one."""
        return self._evaluate(now, claim_notification=True)

    def _evaluate(
        self,
        now: datetime | None,
        *,
        claim_notification: bool,
    ) -> ReminderStatus:
        checked_at = ensure_utc(now or self._clock())
        due_count = self.review_service.due_count(checked_at)
        local_date = checked_at.astimezone().date()
        with self.review_service.database.session() as session:
            self.review_service.database.begin_serialized_write(session)
            state = self._get_or_create_state(session)
            if (
                state.last_snooze_at is not None
                and state.last_snooze_at.astimezone().date() != local_date
            ):
                state.last_snooze_at = None
            today_completed = state.completed_local_date == local_date.isoformat()
            if due_count > 0 and today_completed:
                # A card may become due again later on the same day. In that
                # case the previously completed daily state is no longer true.
                state.completed_local_date = None
                today_completed = False
            with self._session_state_lock:
                local_review_active = self.review_session_active
            self._update_review_lease(
                session,
                active=local_review_active,
                checked_at=checked_at,
            )
            review_session_active = self._has_active_review_lease(
                session,
                checked_at,
            )
            decision = self.policy.evaluate(
                ReminderContext(
                    current_time=checked_at,
                    due_word_count=due_count,
                    last_notification_time=state.last_notification_at,
                    last_snooze_time=state.last_snooze_at,
                    today_completed=today_completed,
                    review_session_active=review_session_active,
                )
            )
            if claim_notification and decision.should_notify:
                state.last_notification_at = checked_at
        self._sync_from_state(state, local_date)
        return ReminderStatus(
            decision=decision,
            due_word_count=due_count,
            estimated_minutes=max(1, math.ceil(due_count / 4)) if due_count else 0,
        )

    def notification_sent(self, now: datetime | None = None) -> None:
        checked_at = ensure_utc(now or self._clock())
        with self.review_service.database.session() as session:
            self.review_service.database.begin_serialized_write(session)
            state = self._get_or_create_state(session)
            state.last_notification_at = checked_at
        self._sync_from_state(state, checked_at.astimezone().date())

    def snooze(self, now: datetime | None = None) -> None:
        checked_at = ensure_utc(now or self._clock())
        with self.review_service.database.session() as session:
            self.review_service.database.begin_serialized_write(session)
            state = self._get_or_create_state(session)
            state.last_snooze_at = checked_at
        self._sync_from_state(state, checked_at.astimezone().date())

    def set_review_session_active(self, active: bool) -> None:
        with self._session_state_lock:
            self.review_session_active = active

    def publish_review_session(
        self,
        active: bool,
        now: datetime | None = None,
    ) -> None:
        checked_at = ensure_utc(now or self._clock())
        self.set_review_session_active(active)
        with self.review_service.database.session() as session:
            self.review_service.database.begin_serialized_write(session)
            self._update_review_lease(
                session,
                active=active,
                checked_at=checked_at,
            )

    def mark_today_completed(self, now: datetime | None = None) -> None:
        checked_at = ensure_utc(now or self._clock())
        local_date = checked_at.astimezone().date()
        with self.review_service.database.session() as session:
            self.review_service.database.begin_serialized_write(session)
            state = self._get_or_create_state(session)
            state.completed_local_date = local_date.isoformat()
        self._sync_from_state(state, local_date)

    def remaining_due_count(self, now: datetime | None = None) -> int:
        return self.review_service.due_count(ensure_utc(now or self._clock()))

    def _load_persisted_state(self) -> None:
        with self.review_service.database.session() as session:
            self.review_service.database.begin_serialized_write(session)
            state = self._get_or_create_state(session)
        self._sync_from_state(state, self._state_date)

    @staticmethod
    def _get_or_create_state(session: Session) -> ReminderRuntimeState:
        state = session.scalar(
            select(ReminderRuntimeState).where(ReminderRuntimeState.id == 1)
        )
        if state is None:
            state = ReminderRuntimeState(id=1)
            session.add(state)
        return state

    def _sync_from_state(
        self,
        state: ReminderRuntimeState,
        local_date: date,
    ) -> None:
        self._state_date = local_date
        self.last_notification_time = state.last_notification_at
        self.last_snooze_time = state.last_snooze_at
        self.today_completed = state.completed_local_date == local_date.isoformat()

    def _update_review_lease(
        self,
        session: Session,
        *,
        active: bool,
        checked_at: datetime,
    ) -> None:
        session.execute(
            delete(ReminderReviewLease).where(
                ReminderReviewLease.lease_until <= checked_at
            )
        )
        lease = session.get(ReminderReviewLease, self.instance_id)
        if not active:
            if lease is not None:
                session.delete(lease)
            return
        lease_until = checked_at + REVIEW_SESSION_LEASE_DURATION
        if lease is None:
            session.add(
                ReminderReviewLease(
                    owner_id=self.instance_id,
                    lease_until=lease_until,
                )
            )
        else:
            lease.lease_until = lease_until

    @staticmethod
    def _has_active_review_lease(session: Session, checked_at: datetime) -> bool:
        return (
            session.scalar(
                select(ReminderReviewLease.owner_id)
                .where(ReminderReviewLease.lease_until > checked_at)
                .limit(1)
            )
            is not None
        )
