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

    def set_review_session_active(self, active: bool) -> None:
        self.session_states.append(active)

    @staticmethod
    def remaining_due_count() -> int:
        return 1


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
