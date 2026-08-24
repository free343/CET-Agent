from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.services.word_detail_service import WordDetailService
from app.ui.vocabulary_page import VocabularyPage


def _wait_until_idle(page: VocabularyPage, app: QApplication) -> None:
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()


def test_vocabulary_page_search_and_detail_entry(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    opened = []
    page = VocabularyPage(
        WordDetailService(database),
        on_open_word=opened.append,
    )
    page.search_input.setText("ADAPT")
    assert page.search() is True
    _wait_until_idle(page, app)

    assert page.word_list.count() == 1
    assert page.word_list.item(0).data(Qt.ItemDataRole.UserRole) == word_id
    page.word_list.setCurrentRow(0)
    assert page.detail_button.isEnabled()
    page.detail_button.click()

    assert len(opened) == 1
    assert opened[0].word == "adapt"
    assert opened[0].trust == "source_validated"
    page.deleteLater()


def test_vocabulary_page_empty_refresh_does_not_load_entire_bank(database) -> None:
    app = QApplication.instance() or QApplication([])
    page = VocabularyPage(WordDetailService(database))

    assert page.refresh() is True
    app.processEvents()

    assert page.word_list.count() == 0
    assert "请输入" in page.status_label.text()
    page.deleteLater()
