"""Personal favorite-word collection page."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.lexical_fact_view import LinkedWordReference
from app.services.wordbook_service import (
    FavoriteUpdate,
    FavoriteWordItem,
    WordbookService,
)
from app.ui.widgets.async_worker import AsyncWorker
from app.ui.widgets.pronunciation_widgets import (
    PronunciationInstallButton,
    PronunciationListRow,
)

logger = logging.getLogger(__name__)


class WordbookPage(QWidget):
    def __init__(
        self,
        service: WordbookService,
        on_open_word: Callable[[LinkedWordReference], None] | None = None,
        *,
        pronunciation_player: object | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.on_open_word = on_open_word
        self.pronunciation_player = pronunciation_player
        self.worker: AsyncWorker | None = None
        self.worker_action: str | None = None
        self._refresh_after_worker = False
        self._items_by_id: dict[int, FavoriteWordItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("收藏单词")
        title.setObjectName("PageTitle")
        self.count_label = QLabel("0 个收藏")
        self.count_label.setStyleSheet("color: #64748b;")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.count_label)
        layout.addLayout(heading)

        subtitle = QLabel("把需要重点关注的词放在这里；收藏不会改变复习计划。")
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(subtitle)

        self.status_label = QLabel("正在加载收藏…")
        self.status_label.setStyleSheet("color: #64748b; padding: 6px 2px;")
        layout.addWidget(self.status_label)
        self.word_list = QListWidget()
        self.word_list.setObjectName("WordbookList")
        self.word_list.currentItemChanged.connect(self._selection_changed)
        self.word_list.itemDoubleClicked.connect(self._item_double_clicked)
        layout.addWidget(self.word_list, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        self.remove_button = QPushButton("取消收藏")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_selected)
        actions.addWidget(self.remove_button)
        self.detail_button = QPushButton("查看词卡")
        self.detail_button.setObjectName("SecondaryButton")
        self.detail_button.setEnabled(False)
        self.detail_button.clicked.connect(self.open_selected)
        actions.addWidget(self.detail_button)
        actions.addWidget(PronunciationInstallButton(pronunciation_player, self))
        layout.addLayout(actions)

    def refresh(self) -> bool:
        if self.worker is not None:
            self._refresh_after_worker = True
            return False
        self.status_label.setText("正在加载收藏…")
        self.remove_button.setEnabled(False)
        self.detail_button.setEnabled(False)
        self.worker_action = "load"
        self.worker = AsyncWorker(self.service.list_favorites, parent=self)
        self.worker.result_ready.connect(self._show_items)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        return True

    def _show_items(self, items: list[FavoriteWordItem]) -> None:
        self._items_by_id = {item.word_id: item for item in items}
        self.word_list.clear()
        for word in items:
            phonetic = f"  {word.phonetic}" if word.phonetic else ""
            example = f"\n{word.example}" if word.example else ""
            translation = (
                f"\n{word.example_translation}" if word.example_translation else ""
            )
            item = QListWidgetItem(
                f"{word.word}{phonetic}    [{word.level.value}]\n"
                f"{word.meaning}{example}{translation}"
            )
            item.setData(Qt.ItemDataRole.UserRole, word.word_id)
            self.word_list.addItem(item)
            row = PronunciationListRow(
                word.word,
                word.phonetic,
                f"{word.meaning}{example}{translation}",
                self.pronunciation_player,
                self.word_list,
            )
            self.word_list.setItemWidget(item, row)
            item.setSizeHint(row.sizeHint())
        self.count_label.setText(f"{len(items)} 个收藏")
        self.status_label.setText(
            "选择词条后可以取消收藏。" if items else "暂无收藏的单词。"
        )

    def remove_selected(self) -> None:
        if self.worker is not None:
            return
        item = self.word_list.currentItem()
        if item is None:
            return
        word_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(word_id, int):
            return
        self.remove_button.setEnabled(False)
        self.worker_action = "remove"
        self.worker = AsyncWorker(
            self.service.set_favorite,
            word_id,
            False,
            parent=self,
        )
        self.worker.result_ready.connect(self._favorite_removed)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def open_selected(self) -> None:
        if self.worker is not None or self.on_open_word is None:
            return
        item = self.word_list.currentItem()
        if item is None:
            return
        word_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(word_id, int):
            return
        favorite = self._items_by_id.get(word_id)
        if favorite is not None:
            self.on_open_word(
                LinkedWordReference(
                    word=favorite.word,
                    meaning=favorite.meaning,
                    trust="source_validated",
                )
            )

    def _item_double_clicked(self, _item: QListWidgetItem) -> None:
        self.open_selected()

    def _favorite_removed(self, result: FavoriteUpdate) -> None:
        if result.is_favorite:
            logger.error("Wordbook removal returned favorite=true")
            return
        self._refresh_after_worker = True

    def _selection_changed(self, current, _previous) -> None:
        self.remove_button.setEnabled(current is not None and self.worker is None)
        self.detail_button.setEnabled(
            current is not None
            and self.worker is None
            and self.on_open_word is not None
        )

    def _task_failed(self, message: str) -> None:
        logger.error(
            "Wordbook action failed action=%s message=%s",
            self.worker_action,
            message,
        )
        if self.worker_action == "load":
            self.word_list.clear()
            self._items_by_id.clear()
            self.count_label.setText("— 个收藏")
            self.remove_button.setEnabled(False)
            self.detail_button.setEnabled(False)
            self.status_label.setText("暂时无法读取收藏，请稍后重试。")
            return
        self.status_label.setText("暂时无法读取或更新收藏，请稍后重试。")
        QMessageBox.warning(self, "CET-Agent", "收藏操作失败，请稍后重试。")

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.worker_action = None
        if self._refresh_after_worker:
            self._refresh_after_worker = False
            self.refresh()
            return
        self._selection_changed(self.word_list.currentItem(), None)
