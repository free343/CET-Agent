from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QListWidget

from app.db.models import WordLevel
from app.services.word_detail_service import WordLookupItem
from app.services.wordbook_service import FavoriteWordItem
from app.ui.theme import APP_STYLESHEET
from app.ui.vocabulary_page import VocabularyPage
from app.ui.wordbook_page import WordbookPage
from app.utils.datetime_utils import UTC


class _AvailablePlayer:
    status = SimpleNamespace(available=True, message="")

    def play(self, _word: str) -> bool:
        return True

    def stop(self) -> None:
        return None


def _assert_first_row_fits(page, app: QApplication) -> None:
    page.setStyleSheet(APP_STYLESHEET)
    page.resize(700, 520)
    page.show()
    app.processEvents()

    word_list: QListWidget = page.word_list
    item = word_list.item(0)
    row = word_list.itemWidget(item)
    assert row is not None
    body = row.findChild(QLabel, "PronunciationListBody")
    assert body is not None
    assert word_list.horizontalScrollBar().maximum() == 0
    assert row.width() <= word_list.viewport().width()
    assert body.height() >= body.heightForWidth(body.width())

    page.resize(500, 520)
    app.processEvents()
    assert word_list.horizontalScrollBar().maximum() == 0
    assert row.width() <= word_list.viewport().width()
    assert body.height() >= body.heightForWidth(body.width())


def test_wordbook_pronunciation_row_reflows_without_clipping() -> None:
    app = QApplication.instance() or QApplication([])
    page = WordbookPage(
        None,  # type: ignore[arg-type]
        pronunciation_player=_AvailablePlayer(),
    )
    page._show_items(
        [
            FavoriteWordItem(
                word_id=1,
                word="extraordinary",
                phonetic="/ɪkˈstrɔːdnri/",
                meaning="非凡的；异乎寻常的；特别的",
                example=(
                    "It was an extraordinary achievement that surprised everyone "
                    "in the research team."
                ),
                level=WordLevel.CET4,
                created_at=datetime.now(UTC),
                example_translation=(
                    "这是一个非凡的成就，令研究团队中的每个人都感到惊讶。"
                ),
            )
        ]
    )

    _assert_first_row_fits(page, app)
    page.deleteLater()
    app.processEvents()


def test_vocabulary_pronunciation_row_reflows_without_clipping() -> None:
    app = QApplication.instance() or QApplication([])
    page = VocabularyPage(
        None,  # type: ignore[arg-type]
        pronunciation_player=_AvailablePlayer(),
    )
    page._show_items(
        [
            WordLookupItem(
                word_id=1,
                word="extraordinary",
                phonetic="/ɪkˈstrɔːdnri/",
                meaning=("非凡的；异乎寻常的；特别的，远远超出通常程度或普通预期的"),
                level="CET4",
            )
        ]
    )

    _assert_first_row_fits(page, app)
    page.deleteLater()
    app.processEvents()
