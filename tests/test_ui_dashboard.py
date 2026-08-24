from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.learning_service import DashboardStats, WrongWordStat
from app.ui.dashboard_page import DashboardPage

STATS = DashboardStats(
    due_count=12,
    today_completed=7,
    seven_day_accuracy=87.5,
    learning_streak=3,
    high_frequency_wrong=(WrongWordStat("adapt", 2),),
    new_count=8,
    future_review_count=2,
    latest_future_review_at=None,
)


def _wait_until_idle(page: DashboardPage, app: QApplication) -> None:
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()


@dataclass
class BlockingDashboardService:
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    calls: int = 0
    worker_thread_id: int | None = None

    def dashboard_stats(self) -> DashboardStats:
        self.calls += 1
        self.worker_thread_id = threading.get_ident()
        self.started.set()
        assert self.release.wait(2)
        return STATS


def test_dashboard_refresh_runs_off_ui_thread_and_renders_result() -> None:
    app = QApplication.instance() or QApplication([])
    service = BlockingDashboardService()
    opened = []
    page = DashboardPage(service, on_open_word=opened.append)
    ui_thread_id = threading.get_ident()

    try:
        assert page.refresh() is True
        assert service.started.wait(1)
        assert service.worker_thread_id != ui_thread_id
        assert page.worker is not None and page.worker.isRunning()

        service.release.set()
        _wait_until_idle(page, app)

        assert page.due.value.text() == "12"
        assert page.new.value.text() == "8"
        assert page.completed.value.text() == "7"
        assert page.accuracy.value.text() == "87.5%"
        assert page.streak.value.text() == "3 天"
        assert page.wrong_words.text() == "adapt  × 2"
        assert page.clock_warning.isHidden() is False
        assert page.wrong_actions_layout.count() == 2
        page.wrong_actions_layout.itemAt(0).widget().click()
        assert [reference.word for reference in opened] == ["adapt"]
    finally:
        service.release.set()
        if page.worker is not None:
            page.worker.wait(2_000)
        page.deleteLater()


def test_dashboard_metric_actions_open_learning_routes() -> None:
    app = QApplication.instance() or QApplication([])

    class ImmediateDashboardService:
        @staticmethod
        def dashboard_stats() -> DashboardStats:
            return STATS

    routes: list[str] = []
    page = DashboardPage(
        ImmediateDashboardService(),
        on_open_new=lambda: routes.append("new"),
        on_open_due=lambda: routes.append("due"),
    )
    page.refresh()
    _wait_until_idle(page, app)

    assert page.new.action_button is not None
    assert page.due.action_button is not None
    page.new.action_button.click()
    page.due.action_button.click()
    assert routes == ["new", "due"]
    page.deleteLater()


def test_dashboard_coalesces_refresh_while_worker_is_running() -> None:
    app = QApplication.instance() or QApplication([])
    service = BlockingDashboardService()
    page = DashboardPage(service)

    try:
        assert page.refresh() is True
        assert service.started.wait(1)
        assert page.refresh() is False

        service.release.set()
        _wait_until_idle(page, app)

        assert service.calls == 2
    finally:
        service.release.set()
        if page.worker is not None:
            page.worker.wait(2_000)
        page.deleteLater()


def test_dashboard_failure_clears_stale_metrics() -> None:
    app = QApplication.instance() or QApplication([])

    class FailingDashboardService:
        @staticmethod
        def dashboard_stats() -> DashboardStats:
            raise RuntimeError("private database detail")

    page = DashboardPage(FailingDashboardService())
    page.due.value.setText("99")
    page.new.value.setText("99")

    assert page.refresh() is True
    _wait_until_idle(page, app)

    assert page.due.value.text() == "—"
    assert page.new.value.text() == "—"
    assert "private" not in page.wrong_words.text()
    assert page.wrong_words.text() == "暂时无法读取学习数据，请稍后重试。"
    assert page.clock_warning.isHidden() is True
    page.deleteLater()
