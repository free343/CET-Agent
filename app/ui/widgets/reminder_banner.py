"""In-app reminder actions complementing the system notification."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class ReminderBanner(QFrame):
    start_requested = Signal()
    snooze_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet(
            "QFrame { background: #eaf2ff; border-bottom: 1px solid #c9dcff; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        self.message = QLabel()
        start = QPushButton("开始复习")
        start.setObjectName("PrimaryButton")
        snooze = QPushButton("30 分钟后提醒")
        start.clicked.connect(self.start_requested)
        snooze.clicked.connect(self.snooze_requested)
        layout.addWidget(self.message)
        layout.addStretch()
        layout.addWidget(start)
        layout.addWidget(snooze)
        self.hide()

    def show_reminder(self, due_count: int, estimated_minutes: int) -> None:
        self.message.setText(
            f"你有 {due_count} 个单词进入复习窗口 · 预计 {estimated_minutes} 分钟"
        )
        self.show()

