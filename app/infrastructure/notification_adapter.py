"""Desktop notification abstraction and PySide6 system-tray implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon, QWidget


class NotificationAdapter(ABC):
    @abstractmethod
    def notify(self, due_word_count: int, estimated_minutes: int) -> None:
        pass


class QtNotificationAdapter(NotificationAdapter):
    def __init__(self, parent: QWidget, on_activated: Callable[[], None]) -> None:
        self.tray = QSystemTrayIcon(parent)
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        self.tray.setIcon(icon)
        self.tray.setToolTip("CET-Agent")
        self.tray.messageClicked.connect(on_activated)
        self.tray.show()

    def notify(self, due_word_count: int, estimated_minutes: int) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray.showMessage(
            "CET-Agent 复习提醒",
            f"你有 {due_word_count} 个单词进入复习窗口\n"
            f"预计需要 {estimated_minutes} 分钟",
            QSystemTrayIcon.MessageIcon.Information,
            10_000,
        )

    def close(self) -> None:
        self.tray.hide()

