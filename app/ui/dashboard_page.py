"""Compact learning overview without ornamental chart dependencies."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.services.learning_service import DashboardStats, LearningService
from app.ui.widgets.async_worker import AsyncWorker

logger = logging.getLogger(__name__)


class MetricCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        caption = QLabel(title)
        caption.setStyleSheet("color: #64748b;")
        self.value = QLabel("—")
        self.value.setObjectName("Metric")
        layout.addWidget(caption)
        layout.addWidget(self.value)


class DashboardPage(QWidget):
    def __init__(self, service: LearningService) -> None:
        super().__init__()
        self.service = service
        self.worker: AsyncWorker | None = None
        self._refresh_pending = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        title = QLabel("学习概览")
        title.setObjectName("PageTitle")
        subtitle = QLabel("今天也用一点时间，把记忆变得更牢固。")
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        metrics = QGridLayout()
        metrics.setSpacing(14)
        self.due = MetricCard("今日待复习")
        self.completed = MetricCard("今日已完成")
        self.accuracy = MetricCard("近 7 天正确率")
        self.streak = MetricCard("连续学习天数")
        for index, card in enumerate(
            (self.due, self.completed, self.accuracy, self.streak)
        ):
            metrics.addWidget(card, 0, index)
        layout.addLayout(metrics)

        wrong_card = QFrame()
        wrong_card.setObjectName("Card")
        wrong_layout = QVBoxLayout(wrong_card)
        wrong_title = QLabel("高频错词")
        wrong_title.setStyleSheet("font-size: 17px; font-weight: 600;")
        self.wrong_words = QLabel("暂无错误记录")
        self.wrong_words.setWordWrap(True)
        self.wrong_words.setStyleSheet("color: #475569; line-height: 1.5;")
        wrong_layout.addWidget(wrong_title)
        wrong_layout.addWidget(self.wrong_words)
        layout.addWidget(wrong_card)
        layout.addStretch()

    def refresh(self) -> bool:
        if self.worker is not None:
            self._refresh_pending = True
            return False
        self.worker = AsyncWorker(self.service.dashboard_stats, parent=self)
        self.worker.result_ready.connect(self._show_stats)
        self.worker.failed.connect(self._show_failure)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        return True

    def _show_stats(self, stats: DashboardStats) -> None:
        self.due.value.setText(str(stats.due_count))
        self.completed.value.setText(str(stats.today_completed))
        self.accuracy.value.setText(f"{stats.seven_day_accuracy:.1f}%")
        self.streak.value.setText(f"{stats.learning_streak} 天")
        if stats.high_frequency_wrong:
            self.wrong_words.setText(
                "    ".join(
                    f"{item.word}  × {item.error_count}"
                    for item in stats.high_frequency_wrong
                )
            )
        else:
            self.wrong_words.setText("暂无错误记录，完成复习后会在这里显示。")

    def _show_failure(self, message: str) -> None:
        logger.error("Could not load dashboard statistics: %s", message)
        for card in (self.due, self.completed, self.accuracy, self.streak):
            card.value.setText("—")
        self.wrong_words.setText("暂时无法读取学习数据，请稍后重试。")

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()
