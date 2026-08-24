from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.wordbook_service import WordbookService
from app.ui.wordbook_page import WordbookPage


def _wait_until_idle(page: WordbookPage, app: QApplication) -> None:
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()


def test_wordbook_page_lists_and_removes_a_favorite(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    service = WordbookService(database)
    service.set_favorite(word_id, True)
    opened = []
    page = WordbookPage(service, on_open_word=opened.append)

    page.refresh()
    _wait_until_idle(page, app)

    assert page.word_list.count() == 1
    assert "adapt" in page.word_list.item(0).text()
    assert "适应；改编" in page.word_list.item(0).text()
    assert "1 个收藏" in page.count_label.text()

    page.word_list.setCurrentRow(0)
    page.detail_button.click()
    assert [reference.word for reference in opened] == ["adapt"]
    page.remove_button.click()
    _wait_until_idle(page, app)

    assert page.word_list.count() == 0
    assert "暂无收藏" in page.status_label.text()
    page.deleteLater()


def test_wordbook_load_runs_off_ui_thread(database, word_id, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    service = WordbookService(database)
    ui_thread_id = threading.get_ident()
    worker_threads: list[int] = []
    original = service.list_favorites

    def tracked_list():
        worker_threads.append(threading.get_ident())
        return original()

    monkeypatch.setattr(service, "list_favorites", tracked_list)
    page = WordbookPage(service)

    page.refresh()
    _wait_until_idle(page, app)

    assert worker_threads
    assert all(thread_id != ui_thread_id for thread_id in worker_threads)
    page.deleteLater()


def test_failed_wordbook_reload_clears_stale_items(database, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    service = WordbookService(database)
    page = WordbookPage(service)
    page.word_list.addItem("stale")

    def fail_to_load():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "list_favorites", fail_to_load)
    page.refresh()
    _wait_until_idle(page, app)

    assert page.word_list.count() == 0
    assert "暂时无法读取收藏" in page.status_label.text()
    page.deleteLater()
