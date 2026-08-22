"""Main navigation shell for the desktop application."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import Settings
from app.infrastructure.notification_adapter import QtNotificationAdapter
from app.services.ai_service import AIService
from app.services.analysis_service import AnalysisService
from app.services.learning_service import LearningService
from app.services.reminder_service import ReminderService
from app.services.review_service import ReviewService
from app.ui.analysis_page import AnalysisPage
from app.ui.chat_page import ChatPage
from app.ui.dashboard_page import DashboardPage
from app.ui.review_page import ReviewPage
from app.ui.settings_page import SettingsPage
from app.ui.theme import APP_STYLESHEET
from app.ui.widgets.reminder_banner import ReminderBanner

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        learning_service: LearningService,
        review_service: ReviewService,
        analysis_service: AnalysisService,
        ai_service: AIService,
        reminder_service: ReminderService,
        settings: Settings,
    ) -> None:
        super().__init__()
        self.setWindowTitle("CET-Agent")
        self.resize(1080, 700)
        self.setMinimumSize(880, 580)
        self.setStyleSheet(APP_STYLESHEET)
        self.reminder_service = reminder_service
        self._closing_after_workers = False

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 10, 14, 18)
        brand = QLabel("CET-Agent")
        brand.setObjectName("Brand")
        sidebar_layout.addWidget(brand)

        self.pages = QStackedWidget()
        self.dashboard_page = DashboardPage(learning_service)
        self.review_page = ReviewPage(
            review_service,
            self.dashboard_page.refresh,
            self._review_session_changed,
        )
        self.analysis_page = AnalysisPage(analysis_service, ai_service)
        self.chat_page = ChatPage(ai_service)
        self.settings_page = SettingsPage(settings)
        pages = (
            ("学习概览", self.dashboard_page),
            ("单词复习", self.review_page),
            ("易混词分析", self.analysis_page),
            ("AI 助手", self.chat_page),
            ("设置", self.settings_page),
        )
        button_group = QButtonGroup(self)
        button_group.setExclusive(True)
        for index, (label, page) in enumerate(pages):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=index: self.show_page(value))
            sidebar_layout.addWidget(button)
            button_group.addButton(button)
            self.pages.addWidget(page)
            if index == 0:
                button.setChecked(True)
        sidebar_layout.addStretch()
        version = QLabel("Local-first · v0.1")
        version.setStyleSheet("color: #718096; padding: 8px 12px;")
        sidebar_layout.addWidget(version)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.reminder_banner = ReminderBanner()
        self.reminder_banner.start_requested.connect(self._start_review_from_reminder)
        self.reminder_banner.snooze_requested.connect(self._snooze_reminder)
        content_layout.addWidget(self.reminder_banner)
        content_layout.addWidget(self.pages, 1)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)
        self.notification_adapter = QtNotificationAdapter(
            self,
            self._start_review_from_reminder,
        )
        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(5 * 60 * 1000)
        self.reminder_timer.timeout.connect(self._check_reminder)
        self.reminder_timer.start()
        QTimer.singleShot(1500, self._check_reminder)
        self.dashboard_page.refresh()

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == 0:
            self.dashboard_page.refresh()
        elif index == 1:
            self.review_page.load_queue()
        elif index == 2:
            self.analysis_page.refresh()

    def _check_reminder(self) -> None:
        try:
            status = self.reminder_service.evaluate()
            if not status.decision.should_notify:
                return
            self.notification_adapter.notify(
                status.due_word_count,
                status.estimated_minutes,
            )
            self.reminder_banner.show_reminder(
                status.due_word_count,
                status.estimated_minutes,
            )
            self.reminder_service.notification_sent()
            logger.info("Review reminder triggered due_count=%s", status.due_word_count)
        except Exception:
            logger.exception("Reminder check failed")

    def _start_review_from_reminder(self) -> None:
        self.reminder_banner.hide()
        self.show_page(1)
        self.raise_()
        self.activateWindow()

    def _snooze_reminder(self) -> None:
        self.reminder_service.snooze()
        self.reminder_banner.hide()
        logger.info("Review reminder snoozed")

    def _review_session_changed(self, active: bool) -> None:
        self.reminder_service.set_review_session_active(active)
        if active:
            # Manual navigation to Review must dismiss an already visible
            # reminder just like the banner's own "start review" action.
            self.reminder_banner.hide()
        if not active and self.reminder_service.remaining_due_count() == 0:
            self.reminder_service.mark_today_completed()

    def closeEvent(self, event) -> None:
        active_workers = self._active_workers()
        if active_workers:
            event.ignore()
            if not self._closing_after_workers:
                self._closing_after_workers = True
                self.reminder_timer.stop()
                self.reminder_banner.hide()
                self.notification_adapter.close()
                self.hide()
                logger.info(
                    "Window close deferred until %s background task(s) finish",
                    len(active_workers),
                )
                for worker in active_workers:
                    worker.finished.connect(self._schedule_deferred_close)
            return
        self.notification_adapter.close()
        super().closeEvent(event)

    def _active_workers(self) -> list:
        workers = (self.analysis_page.worker, self.chat_page.worker)
        return [worker for worker in workers if worker is not None and worker.isRunning()]

    def _schedule_deferred_close(self) -> None:
        QTimer.singleShot(0, self._close_if_idle)

    def _close_if_idle(self) -> None:
        if self._closing_after_workers and not self._active_workers():
            self._closing_after_workers = False
            self.close()
