"""Compact learning overview without ornamental chart dependencies."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.learning_service import DashboardStats, LearningService
from app.services.lexical_fact_view import LinkedWordReference
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
    def __init__(
        self,
        service: LearningService,
        on_open_word: Callable[[LinkedWordReference], None] | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.on_open_word = on_open_word
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
        self.new = MetricCard("待学新词")
        self.due = MetricCard("到期复习")
        self.completed = MetricCard("今日学习记录")
        self.accuracy = MetricCard("近 7 天正确率")
        self.streak = MetricCard("连续学习天数")
        for card, row, column in (
            (self.new, 0, 0),
            (self.due, 0, 1),
            (self.completed, 0, 2),
            (self.accuracy, 1, 0),
            (self.streak, 1, 1),
        ):
            metrics.addWidget(card, row, column)
        for column in range(3):
            metrics.setColumnStretch(column, 1)
        layout.addLayout(metrics)

        self.clock_warning = QLabel("")
        self.clock_warning.setObjectName("ClockWarning")
        self.clock_warning.setWordWrap(True)
        self.clock_warning.setStyleSheet(
            "background: #fff7ed; color: #9a3412; border: 1px solid #fdba74; "
            "border-radius: 8px; padding: 10px 12px;"
        )
        self.clock_warning.hide()
        layout.addWidget(self.clock_warning)

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
        self.wrong_actions = QWidget()
        self.wrong_actions_layout = QHBoxLayout(self.wrong_actions)
        self.wrong_actions_layout.setContentsMargins(0, 4, 0, 0)
        self.wrong_actions_layout.setSpacing(8)
        self.wrong_actions_layout.addStretch()
        wrong_layout.addWidget(self.wrong_actions)
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
        self.new.value.setText(str(stats.new_count))
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
            self._show_wrong_actions(stats)
        else:
            self.wrong_words.setText("暂无错误记录，完成复习后会在这里显示。")
            self._clear_wrong_actions()
        if stats.future_review_count:
            latest = (
                stats.latest_future_review_at.astimezone().strftime("%Y-%m-%d %H:%M")
                if stats.latest_future_review_at is not None
                else "未知时间"
            )
            self.clock_warning.setText(
                f"检测到 {stats.future_review_count} 条学习记录晚于当前系统时间"
                f"（最晚 {latest}）。这通常由系统时钟回拨造成，部分复习可能暂时不显示；"
                "请先校准 Windows 日期、时间和时区。应用不会自动改写这些记录。"
            )
            self.clock_warning.show()
        else:
            self.clock_warning.clear()
            self.clock_warning.hide()

    def _show_failure(self, message: str) -> None:
        logger.error("Could not load dashboard statistics: %s", message)
        for card in (
            self.new,
            self.due,
            self.completed,
            self.accuracy,
            self.streak,
        ):
            card.value.setText("—")
        self.clock_warning.clear()
        self.clock_warning.hide()
        self.wrong_words.setText("暂时无法读取学习数据，请稍后重试。")
        self._clear_wrong_actions()

    def _show_wrong_actions(self, stats: DashboardStats) -> None:
        self._clear_wrong_actions()
        if self.on_open_word is None:
            return
        for item in stats.high_frequency_wrong:
            button = QPushButton(f"{item.word} · 词卡")
            button.setObjectName("LinkButton")
            button.clicked.connect(
                lambda _checked=False, word=item.word: self._open_word(word)
            )
            self.wrong_actions_layout.insertWidget(
                self.wrong_actions_layout.count() - 1,
                button,
            )

    def _clear_wrong_actions(self) -> None:
        while self.wrong_actions_layout.count() > 1:
            item = self.wrong_actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _open_word(self, word: str) -> None:
        if self.on_open_word is not None:
            self.on_open_word(LinkedWordReference(word=word, trust="source_validated"))

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()
