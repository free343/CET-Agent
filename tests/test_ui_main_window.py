from __future__ import annotations

import os
import threading
from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow

from app.domain.reminder_policy import ReminderDecision
from app.services.reminder_service import ReminderStatus
from app.ui.main_window import (
    MAX_QT_TIMER_INTERVAL_MS,
    MainWindow,
    reminder_wakeup_delay_ms,
)
from app.ui.widgets.reminder_banner import ReminderBanner
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


class ReminderQueueHarness(QMainWindow):
    _enqueue_reminder_task = MainWindow._enqueue_reminder_task
    _start_next_reminder_task = MainWindow._start_next_reminder_task
    _reminder_worker_finished = MainWindow._reminder_worker_finished

    def __init__(self) -> None:
        super().__init__()
        self.reminder_worker = None
        self.reminder_worker_action = None
        self._reminder_tasks = deque()
        self.results: list[object] = []
        self.failures: list[str] = []

    def _reminder_task_succeeded(self, result: object) -> None:
        self.results.append(result)

    def _reminder_task_failed(self, message: str) -> None:
        self.failures.append(message)


class FakeReminderService:
    def __init__(self) -> None:
        self.session_states: list[bool] = []
        self.completed = False

    def set_review_session_active(self, active: bool) -> None:
        self.session_states.append(active)

    @staticmethod
    def remaining_due_count() -> int:
        return 1

    def mark_today_completed(self) -> None:
        self.completed = True

    @staticmethod
    def publish_review_session(_active: bool) -> None:
        pass


def test_starting_review_hides_visible_reminder_banner() -> None:
    app = QApplication.instance() or QApplication([])
    banner = ReminderBanner()
    banner.show_reminder(13, 4)
    reminder_service = FakeReminderService()
    review_page = object()
    queued: list[tuple[str, object, bool]] = []

    def enqueue(action, function, *, coalesce=False):
        queued.append((action, function, coalesce))

    window_like = SimpleNamespace(
        reminder_service=reminder_service,
        reminder_banner=banner,
        _closing_after_workers=False,
        pages=SimpleNamespace(currentWidget=lambda: review_page),
        review_page=review_page,
        _enqueue_reminder_task=enqueue,
    )

    MainWindow._review_session_changed(window_like, True)
    app.processEvents()

    assert reminder_service.session_states == [True]
    assert banner.isHidden() is True
    assert [(action, coalesce) for action, _function, coalesce in queued] == [
        ("publish_review_session", False)
    ]
    banner.deleteLater()


def test_hidden_review_worker_cannot_republish_active_lease() -> None:
    reminder_service = FakeReminderService()
    review_page = object()
    queued: list[object] = []
    window_like = SimpleNamespace(
        _closing_after_workers=False,
        pages=SimpleNamespace(currentWidget=lambda: object()),
        review_page=review_page,
        reminder_service=reminder_service,
        reminder_banner=ReminderBanner(),
        _enqueue_reminder_task=lambda *args, **kwargs: queued.append((args, kwargs)),
    )

    MainWindow._review_session_changed(window_like, True)

    assert reminder_service.session_states == []
    assert queued == []
    window_like.reminder_banner.deleteLater()


def test_active_workers_include_dashboard_and_review_tasks() -> None:
    class FakeWorker:
        @staticmethod
        def isRunning() -> bool:
            return True

    dashboard_worker = FakeWorker()
    review_worker = FakeWorker()
    assistant_worker = FakeWorker()
    window_like = SimpleNamespace(
        dashboard_page=SimpleNamespace(worker=dashboard_worker),
        review_page=SimpleNamespace(
            worker=review_worker,
            assistant_panel=SimpleNamespace(worker=assistant_worker),
        ),
        analysis_page=SimpleNamespace(worker=None),
        chat_page=SimpleNamespace(worker=None),
        reminder_worker=None,
    )

    assert MainWindow._active_workers(window_like) == [
        dashboard_worker,
        review_worker,
        assistant_worker,
    ]


def test_close_watcher_recovers_worker_that_finished_before_signal_connection() -> None:
    class FakeSignal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback) -> None:
            self.callbacks.append(callback)

    class JustFinishedWorker:
        def __init__(self) -> None:
            self.watched = False
            self.finished = FakeSignal()

        def property(self, _name: str) -> bool:
            return self.watched

        def setProperty(self, _name: str, value: bool) -> None:
            self.watched = value

        @staticmethod
        def isRunning() -> bool:
            return False

    scheduled: list[bool] = []
    window_like = SimpleNamespace(
        _schedule_deferred_close=lambda: scheduled.append(True)
    )
    worker = JustFinishedWorker()

    MainWindow._watch_worker_for_close(window_like, worker)
    MainWindow._watch_worker_for_close(window_like, worker)

    assert len(worker.finished.callbacks) == 1
    assert scheduled == [True]


def test_inactive_review_enqueues_completion_check() -> None:
    reminder_service = FakeReminderService()
    queued: list[tuple[str, object, bool]] = []
    completion_task = lambda: 0

    def enqueue(action, function, *, coalesce=False):
        queued.append((action, function, coalesce))

    window_like = SimpleNamespace(
        reminder_service=reminder_service,
        reminder_banner=ReminderBanner(),
        _mark_review_complete_if_empty=completion_task,
        _enqueue_reminder_task=enqueue,
    )

    MainWindow._review_session_changed(window_like, False)

    assert reminder_service.session_states == [False]
    assert [action for action, _function, _coalesce in queued] == [
        "publish_review_session",
        "complete_if_empty",
    ]
    assert queued[1] == ("complete_if_empty", completion_task, True)
    window_like.reminder_banner.deleteLater()


def test_reminder_check_enqueues_atomic_evaluation() -> None:
    queued: list[tuple[str, object, bool]] = []

    def evaluate_and_claim():
        return None

    def enqueue(action, function, *, coalesce=False):
        queued.append((action, function, coalesce))

    window_like = SimpleNamespace(
        _closing_after_workers=False,
        _shutdown_started=False,
        reminder_service=SimpleNamespace(evaluate_and_claim=evaluate_and_claim),
        _enqueue_reminder_task=enqueue,
    )

    MainWindow._check_reminder(window_like)

    assert queued == [("evaluate", evaluate_and_claim, True)]


def test_reminder_wakeup_delay_is_exact_bounded_and_never_negative() -> None:
    assert (
        reminder_wakeup_delay_ms(
            NOW + timedelta(minutes=30),
            now=NOW,
        )
        == 30 * 60 * 1_000
    )
    assert (
        reminder_wakeup_delay_ms(
            NOW - timedelta(seconds=1),
            now=NOW,
        )
        == 0
    )
    assert (
        reminder_wakeup_delay_ms(
            NOW + timedelta(days=100),
            now=NOW,
        )
        == MAX_QT_TIMER_INTERVAL_MS
    )


def test_reminder_results_schedule_persisted_wakeup_time() -> None:
    scheduled: list[datetime | None] = []
    window_like = SimpleNamespace(
        reminder_worker_action="evaluate",
        _schedule_reminder_wakeup=scheduled.append,
        _closing_after_workers=False,
    )
    wake_at = NOW + timedelta(minutes=30)
    status = ReminderStatus(
        decision=ReminderDecision(False, "snoozed"),
        due_word_count=4,
        estimated_minutes=1,
        next_evaluation_at=wake_at,
    )

    MainWindow._reminder_task_succeeded(window_like, status)
    window_like.reminder_worker_action = "snooze"
    MainWindow._reminder_task_succeeded(window_like, wake_at)

    assert scheduled == [wake_at, wake_at]


def test_reminder_task_queue_serializes_work_off_ui_thread() -> None:
    app = QApplication.instance() or QApplication([])
    harness = ReminderQueueHarness()
    first_started = threading.Event()
    release_first = threading.Event()
    ui_thread_id = threading.get_ident()
    calls: list[tuple[str, int]] = []

    def first_task() -> str:
        calls.append(("first", threading.get_ident()))
        first_started.set()
        assert release_first.wait(2)
        return "first-result"

    def second_task() -> str:
        calls.append(("second", threading.get_ident()))
        return "second-result"

    try:
        assert harness._enqueue_reminder_task("first", first_task) is True
        assert first_started.wait(1)
        assert harness._enqueue_reminder_task("second", second_task) is True
        assert [name for name, _thread_id in calls] == ["first"]

        release_first.set()
        while harness.reminder_worker is not None or harness._reminder_tasks:
            worker = harness.reminder_worker
            if worker is not None:
                assert worker.wait(2_000)
            app.processEvents()

        assert [name for name, _thread_id in calls] == ["first", "second"]
        assert all(thread_id != ui_thread_id for _name, thread_id in calls)
        assert harness.results == ["first-result", "second-result"]
        assert harness.failures == []
    finally:
        release_first.set()
        if harness.reminder_worker is not None:
            harness.reminder_worker.wait(2_000)
        harness.deleteLater()
