"""Main navigation shell for the desktop application."""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Callable
from datetime import datetime
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
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
from app.infrastructure.pronunciation import PronunciationPlayer
from app.services.acquisition_service import AcquisitionService
from app.services.ai_service import AIService
from app.services.analysis_service import AnalysisService
from app.services.learning_aid_feedback_service import LearningAidFeedbackService
from app.services.learning_service import LearningService
from app.services.mastery_service import MasteryService
from app.services.practice_service import PracticeService
from app.services.reminder_service import ReminderService, ReminderStatus
from app.services.review_service import ReviewService
from app.services.word_detail_service import WordDetailService
from app.services.wordbook_service import WordbookService
from app.ui.acquisition_page import AcquisitionPage
from app.ui.analysis_page import AnalysisPage
from app.ui.chat_page import ChatPage
from app.ui.dashboard_page import DashboardPage
from app.ui.mastered_page import MasteredPage
from app.ui.review_page import ReviewPage, StudySessionMode
from app.ui.settings_page import SettingsPage
from app.ui.theme import APP_STYLESHEET
from app.ui.vocabulary_page import VocabularyPage
from app.ui.widgets.async_worker import AsyncWorker
from app.ui.widgets.reminder_banner import ReminderBanner
from app.ui.word_detail_controller import WordDetailController
from app.ui.wordbook_page import WordbookPage
from app.utils.datetime_utils import ensure_utc, utc_now

logger = logging.getLogger(__name__)
MAX_QT_TIMER_INTERVAL_MS = 2_147_483_647
DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 760
MINIMUM_WINDOW_WIDTH = 960
MINIMUM_WINDOW_HEIGHT = 620


def reminder_wakeup_delay_ms(
    wake_at: datetime,
    *,
    now: datetime | None = None,
) -> int:
    remaining_seconds = (
        ensure_utc(wake_at) - ensure_utc(now or utc_now())
    ).total_seconds()
    return min(
        MAX_QT_TIMER_INTERVAL_MS,
        max(0, math.ceil(remaining_seconds * 1_000)),
    )


class MainWindow(QMainWindow):
    def __init__(
        self,
        learning_service: LearningService,
        review_service: ReviewService,
        analysis_service: AnalysisService,
        ai_service: AIService,
        reminder_service: ReminderService,
        wordbook_service: WordbookService,
        learning_aid_feedback_service: LearningAidFeedbackService,
        practice_service: PracticeService,
        settings: Settings,
        acquisition_service: AcquisitionService | None = None,
        mastery_service: MasteryService | None = None,
        word_detail_service: WordDetailService | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("CET-Agent")
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(MINIMUM_WINDOW_WIDTH, MINIMUM_WINDOW_HEIGHT)
        self.setStyleSheet(APP_STYLESHEET)
        self.reminder_service = reminder_service
        self._closing_after_workers = False
        self._shutdown_started = False
        self._pronunciation_refresh_pending = False
        self.reminder_worker: AsyncWorker | None = None
        self.reminder_worker_action: str | None = None
        self._reminder_tasks: deque[tuple[str, Callable[[], object]]] = deque()
        self.acquisition_service = acquisition_service or AcquisitionService(
            review_service.database,
            review_service.study_level,
        )
        self.mastery_service = mastery_service or MasteryService(
            review_service.database
        )
        self.pronunciation_player = PronunciationPlayer(self)
        detail_service = word_detail_service or WordDetailService(
            review_service.database
        )
        self.word_detail_controller = WordDetailController(
            detail_service,
            self,
            pronunciation_player=self.pronunciation_player,
        )
        linked_word_callback = self.word_detail_controller.open

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
        self.dashboard_page = DashboardPage(
            learning_service,
            on_open_word=linked_word_callback,
            on_open_new=self._open_learning_route,
            on_open_due=self._open_review_route,
        )
        self.vocabulary_page = VocabularyPage(
            detail_service,
            on_open_word=linked_word_callback,
            pronunciation_player=self.pronunciation_player,
        )
        self.wordbook_page = WordbookPage(
            wordbook_service,
            on_open_word=linked_word_callback,
            pronunciation_player=self.pronunciation_player,
        )
        self.mastered_page = MasteredPage(
            self.mastery_service,
            on_open_word=linked_word_callback,
            pronunciation_player=self.pronunciation_player,
        )
        self.learning_page = AcquisitionPage(
            self.acquisition_service,
            on_changed=self._review_completed,
            on_session_state_changed=self._review_session_changed,
            assistant_service=ai_service,
            wordbook_service=wordbook_service,
            mastery_service=self.mastery_service,
            on_linked_word=linked_word_callback,
            pronunciation_player=self.pronunciation_player,
        )
        self.review_page = ReviewPage(
            review_service,
            on_reviewed=self._review_completed,
            on_session_state_changed=self._review_session_changed,
            assistant_service=ai_service,
            wordbook_service=wordbook_service,
            learning_aid_feedback_service=learning_aid_feedback_service,
            mastery_service=self.mastery_service,
            session_mode=StudySessionMode.REVIEW,
            on_linked_word=linked_word_callback,
            pronunciation_player=self.pronunciation_player,
        )
        self.practice_page = ReviewPage(
            review_service,
            on_reviewed=self._review_completed,
            on_session_state_changed=self._review_session_changed,
            assistant_service=ai_service,
            wordbook_service=wordbook_service,
            learning_aid_feedback_service=learning_aid_feedback_service,
            mastery_service=self.mastery_service,
            session_mode=StudySessionMode.PRACTICE,
            practice_service=practice_service,
            on_linked_word=linked_word_callback,
            pronunciation_player=self.pronunciation_player,
        )
        self.study_pages = (
            self.learning_page,
            self.review_page,
            self.practice_page,
        )
        self.analysis_page = AnalysisPage(
            analysis_service,
            ai_service,
            on_start_practice=self._start_confusion_practice,
            on_open_word=linked_word_callback,
        )
        self.chat_page = ChatPage(ai_service)
        self.settings_page = SettingsPage(settings, self.pronunciation_player)
        pages = (
            ("学习概览", self.dashboard_page),
            ("词汇查找", self.vocabulary_page),
            ("学习新词", self.learning_page),
            ("到期复习", self.review_page),
            ("自由复习", self.practice_page),
            ("收藏单词", self.wordbook_page),
            ("已掌握单词", self.mastered_page),
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
            button.clicked.connect(
                lambda _checked=False, value=index: self.show_page(value)
            )
            sidebar_layout.addWidget(button)
            button_group.addButton(button)
            self.pages.addWidget(page)
            if index == 0:
                button.setChecked(True)
        sidebar_layout.addStretch()
        version = QLabel("Local-first · v0.1")
        version.setObjectName("SidebarFooter")
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
            self._snooze_reminder,
        )
        self.pronunciation_player.settings_opened.connect(
            self._schedule_pronunciation_refresh
        )
        self.pronunciation_refresh_timer = QTimer(self)
        self.pronunciation_refresh_timer.setSingleShot(True)
        self.pronunciation_refresh_timer.setInterval(1500)
        self.pronunciation_refresh_timer.timeout.connect(self._refresh_pronunciation)
        application = QApplication.instance()
        if application is not None:
            application.applicationStateChanged.connect(self._application_state_changed)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(5 * 60 * 1000)
        self.reminder_timer.timeout.connect(self._check_reminder)
        self.reminder_timer.start()
        self.reminder_wakeup_timer = QTimer(self)
        self.reminder_wakeup_timer.setSingleShot(True)
        self.reminder_wakeup_timer.timeout.connect(self._check_reminder)
        QTimer.singleShot(1500, self._check_reminder)
        self.dashboard_page.refresh()

    def _schedule_pronunciation_refresh(self) -> None:
        if self._shutdown_started:
            return
        self._pronunciation_refresh_pending = True
        self.pronunciation_refresh_timer.start()

    def _application_state_changed(self, state) -> None:
        if self._shutdown_started:
            return
        if (
            state == Qt.ApplicationState.ApplicationActive
            and self._pronunciation_refresh_pending
        ):
            self._schedule_pronunciation_refresh()

    def _refresh_pronunciation(self) -> None:
        if self._shutdown_started or not self._pronunciation_refresh_pending:
            return
        application = QApplication.instance()
        if (
            application is not None
            and application.applicationState() != Qt.ApplicationState.ApplicationActive
        ):
            self._schedule_pronunciation_refresh()
            return
        self._pronunciation_refresh_pending = False
        self.pronunciation_player.refresh()

    def show_page(self, index: int) -> None:
        target = self.pages.widget(index)
        if target is None:
            return
        study_pages = getattr(self, "study_pages", (self.review_page,))
        current = self.pages.currentWidget()
        if current in study_pages and target is not current:
            self._review_session_changed(False)
        self.pages.setCurrentIndex(index)
        if target is self.dashboard_page:
            self.dashboard_page.refresh()
        elif target is self.vocabulary_page:
            self.vocabulary_page.refresh()
        elif target in study_pages:
            self._review_session_changed(True)
            target.load_queue()
        elif target is self.wordbook_page:
            self.wordbook_page.refresh()
        elif target is self.mastered_page:
            self.mastered_page.refresh()
        elif target is self.analysis_page:
            self.analysis_page.refresh()

    def _open_learning_route(self) -> None:
        self.show_page(self.pages.indexOf(self.learning_page))

    def _open_review_route(self) -> None:
        self.show_page(self.pages.indexOf(self.review_page))

    def _check_reminder(self) -> None:
        if self._shutdown_started:
            return
        self._enqueue_reminder_task(
            "evaluate",
            self.reminder_service.evaluate_and_claim,
            coalesce=True,
        )

    def _start_review_from_reminder(self) -> None:
        self.reminder_banner.hide()
        self.show_page(self.pages.indexOf(self.review_page))
        self.raise_()
        self.activateWindow()

    def _start_confusion_practice(
        self,
        word_ids: tuple[int, ...],
        label: str,
    ) -> None:
        if not self.practice_page.set_confusion_cluster(word_ids, label):
            self.analysis_page.status.setText(
                "自由复习正在保存或加载，请稍后再启动词簇练习。"
            )
            return
        self.show_page(self.pages.indexOf(self.practice_page))

    def _snooze_reminder(self) -> None:
        self.reminder_banner.hide()
        self._enqueue_reminder_task("snooze", self.reminder_service.snooze)

    def _review_session_changed(self, active: bool) -> None:
        study_pages = getattr(self, "study_pages", None)
        if study_pages is None:
            review_page = getattr(self, "review_page", None)
            study_pages = (review_page,) if review_page is not None else ()
        if active and (
            self._closing_after_workers or self.pages.currentWidget() not in study_pages
        ):
            return
        self.reminder_service.set_review_session_active(active)
        self._enqueue_reminder_task(
            "publish_review_session",
            partial(self.reminder_service.publish_review_session, active),
        )
        if active:
            # Manual navigation to Review must dismiss an already visible
            # reminder just like the banner's own "start review" action.
            self.reminder_banner.hide()
        if not active:
            self._enqueue_reminder_task(
                "complete_if_empty",
                self._mark_review_complete_if_empty,
                coalesce=True,
            )

    def _review_completed(self) -> None:
        self.dashboard_page.refresh()
        self._review_session_changed(True)

    def _mark_review_complete_if_empty(self) -> int:
        remaining_due = self.reminder_service.remaining_due_count()
        if remaining_due == 0:
            self.reminder_service.mark_today_completed()
        return remaining_due

    def _enqueue_reminder_task(
        self,
        action: str,
        function: Callable[[], object],
        *,
        coalesce: bool = False,
    ) -> bool:
        if coalesce and (
            self.reminder_worker_action == action
            or any(
                queued_action == action
                for queued_action, _function in self._reminder_tasks
            )
        ):
            return False
        self._reminder_tasks.append((action, function))
        self._start_next_reminder_task()
        return True

    def _start_next_reminder_task(self) -> None:
        if self.reminder_worker is not None or not self._reminder_tasks:
            return
        action, function = self._reminder_tasks.popleft()
        self.reminder_worker_action = action
        self.reminder_worker = AsyncWorker(function, parent=self)
        self.reminder_worker.result_ready.connect(self._reminder_task_succeeded)
        self.reminder_worker.failed.connect(self._reminder_task_failed)
        self.reminder_worker.finished.connect(self._reminder_worker_finished)
        self.reminder_worker.start()

    def _reminder_task_succeeded(self, result: object) -> None:
        action = self.reminder_worker_action
        if action == "evaluate":
            if not isinstance(result, ReminderStatus):
                logger.error("Reminder evaluation returned an invalid result")
                return
            self._schedule_reminder_wakeup(result.next_evaluation_at)
            if not result.decision.should_notify or self._closing_after_workers:
                return
            self.notification_adapter.notify(
                result.due_word_count,
                result.estimated_minutes,
            )
            self.reminder_banner.show_reminder(
                result.due_word_count,
                result.estimated_minutes,
            )
            logger.info(
                "Review reminder triggered due_count=%s",
                result.due_word_count,
            )
        elif action == "snooze":
            if isinstance(result, datetime):
                self._schedule_reminder_wakeup(result)
            else:
                logger.error("Reminder snooze returned an invalid wake-up time")
            logger.info("Review reminder snoozed")

    def _schedule_reminder_wakeup(self, wake_at: datetime | None) -> None:
        if wake_at is None:
            self.reminder_wakeup_timer.stop()
            return
        self.reminder_wakeup_timer.start(reminder_wakeup_delay_ms(wake_at))

    def _reminder_task_failed(self, message: str) -> None:
        logger.error(
            "Reminder background action failed action=%s message=%s",
            self.reminder_worker_action,
            message,
        )

    def _reminder_worker_finished(self) -> None:
        if self.reminder_worker is not None:
            self.reminder_worker.deleteLater()
        self.reminder_worker = None
        self.reminder_worker_action = None
        self._start_next_reminder_task()

    def closeEvent(self, event) -> None:
        if not self._shutdown_started:
            self._shutdown_started = True
            self.reminder_timer.stop()
            self.reminder_wakeup_timer.stop()
            self.reminder_service.set_review_session_active(False)
            self.pronunciation_player.stop()
            if self.word_detail_controller is not None:
                self.word_detail_controller.close()
            self._enqueue_reminder_task(
                "release_review_session",
                partial(self.reminder_service.publish_review_session, False),
            )
        active_workers = self._active_workers()
        if active_workers:
            event.ignore()
            if not self._closing_after_workers:
                self._closing_after_workers = True
                self.reminder_banner.hide()
                self.notification_adapter.close()
                self.hide()
                logger.info(
                    "Window close deferred until %s background task(s) finish",
                    len(active_workers),
                )
                for worker in active_workers:
                    self._watch_worker_for_close(worker)
            return
        self.notification_adapter.close()
        super().closeEvent(event)

    def _active_workers(self) -> list:
        study_pages = getattr(self, "study_pages", (self.review_page,))
        workers = [self.dashboard_page.worker]
        for page in study_pages:
            assistant = getattr(page, "assistant_panel", None)
            workers.extend((page.worker, getattr(assistant, "worker", None)))
        workers.extend(
            (
                self.wordbook_page.worker,
                getattr(getattr(self, "vocabulary_page", None), "worker", None),
                getattr(getattr(self, "mastered_page", None), "worker", None),
                self.analysis_page.worker,
                self.chat_page.worker,
                self.reminder_worker,
            )
        )
        detail_controller = getattr(self, "word_detail_controller", None)
        if detail_controller is not None:
            workers.extend(detail_controller.active_workers())
        return [
            worker for worker in workers if worker is not None and worker.isRunning()
        ]

    def _schedule_deferred_close(self) -> None:
        QTimer.singleShot(0, self._close_if_idle)

    def _watch_worker_for_close(self, worker) -> None:
        if worker.property("cet_close_watched"):
            return
        worker.setProperty("cet_close_watched", True)
        worker.finished.connect(self._schedule_deferred_close)
        # The worker can finish between _active_workers() and this connection.
        # Re-check after connecting so a fast final database task cannot hide
        # the window forever after its finished signal was already emitted.
        if not worker.isRunning():
            self._schedule_deferred_close()

    def _close_if_idle(self) -> None:
        if not self._closing_after_workers:
            return
        active_workers = self._active_workers()
        if active_workers:
            for worker in active_workers:
                self._watch_worker_for_close(worker)
            return
        self._closing_after_workers = False
        self.close()
        application = QApplication.instance()
        if application is not None:
            application.quit()
