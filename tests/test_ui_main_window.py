from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.widgets.reminder_banner import ReminderBanner


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


def test_starting_review_hides_visible_reminder_banner() -> None:
    app = QApplication.instance() or QApplication([])
    banner = ReminderBanner()
    banner.show_reminder(13, 4)
    reminder_service = FakeReminderService()
    window_like = SimpleNamespace(
        reminder_service=reminder_service,
        reminder_banner=banner,
    )

    MainWindow._review_session_changed(window_like, True)
    app.processEvents()

    assert reminder_service.session_states == [True]
    assert banner.isHidden() is True
    banner.deleteLater()


def test_active_workers_include_dashboard_and_review_tasks() -> None:
    class FakeWorker:
        @staticmethod
        def isRunning() -> bool:
            return True

    dashboard_worker = FakeWorker()
    review_worker = FakeWorker()
    window_like = SimpleNamespace(
        dashboard_page=SimpleNamespace(worker=dashboard_worker),
        review_page=SimpleNamespace(worker=review_worker),
        analysis_page=SimpleNamespace(worker=None),
        chat_page=SimpleNamespace(worker=None),
    )

    assert MainWindow._active_workers(window_like) == [
        dashboard_worker,
        review_worker,
    ]


def test_failed_remaining_count_does_not_escape_ui_callback() -> None:
    class FailingReminderService(FakeReminderService):
        @staticmethod
        def remaining_due_count() -> int:
            raise RuntimeError("database unavailable")

    reminder_service = FailingReminderService()
    window_like = SimpleNamespace(
        reminder_service=reminder_service,
        reminder_banner=ReminderBanner(),
    )

    MainWindow._review_session_changed(window_like, False)

    assert reminder_service.session_states == [False]
    assert reminder_service.completed is False
    window_like.reminder_banner.deleteLater()
