"""Bounded local vocabulary lookup and read-only detail entry point."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.lexical_fact_view import LinkedWordReference
from app.services.word_detail_service import WordDetailService, WordLookupItem
from app.ui.widgets.async_worker import AsyncWorker
from app.ui.widgets.pronunciation_widgets import (
    PronunciationInstallButton,
    PronunciationListRow,
)

logger = logging.getLogger(__name__)
LOOKUP_LIMIT = 50


class VocabularyPage(QWidget):
    """Search the local bank without creating study obligations."""

    def __init__(
        self,
        service: WordDetailService,
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
        self._pending_query: str | None = None
        self._results: dict[int, WordLookupItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        title = QLabel("词汇查找")
        title.setObjectName("PageTitle")
        self.count_label = QLabel("输入英文单词开始查找")
        self.count_label.setStyleSheet("color: #64748b;")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.count_label)
        layout.addLayout(heading)

        subtitle = QLabel(
            "在本地 4,611 词库中按精确词或前缀查找；双击词条或点击按钮打开只读词卡。"
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(subtitle)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("例如：main、adapt、gov…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self.search)
        search_row.addWidget(self.search_input, 1)
        self.search_button = QPushButton("查找")
        self.search_button.setObjectName("PrimaryButton")
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.status_label = QLabel("请输入一个英文单词或前缀。")
        self.status_label.setStyleSheet("color: #64748b; padding: 6px 2px;")
        layout.addWidget(self.status_label)

        self.word_list = QListWidget()
        self.word_list.setObjectName("VocabularyList")
        self.word_list.currentItemChanged.connect(self._selection_changed)
        self.word_list.itemDoubleClicked.connect(self._item_double_clicked)
        layout.addWidget(self.word_list, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        self.detail_button = QPushButton("查看词卡")
        self.detail_button.setObjectName("SecondaryButton")
        self.detail_button.setEnabled(False)
        self.detail_button.clicked.connect(self.open_selected)
        actions.addWidget(self.detail_button)
        actions.addWidget(PronunciationInstallButton(pronunciation_player, self))
        layout.addLayout(actions)

    def refresh(self) -> bool:
        """Refresh an existing query without implicitly loading all 4,611 words."""
        if self.search_input.text().strip():
            return self.search()
        self._clear_results()
        self.status_label.setText("请输入一个英文单词或前缀。")
        return True

    def search(self) -> bool:
        query = self.search_input.text().strip()
        if self.worker is not None:
            self._pending_query = query
            return False
        if not query:
            self._clear_results()
            self.status_label.setText("请输入一个英文单词或前缀。")
            return True
        self._set_busy(True)
        self.status_label.setText("正在查找本地词库…")
        self.worker_action = "search"
        self.worker = AsyncWorker(
            partial(self.service.search_words, query, LOOKUP_LIMIT),
            parent=self,
        )
        self.worker.result_ready.connect(self._show_items)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        return True

    def _show_items(self, items: list[WordLookupItem]) -> None:
        self._results = {item.word_id: item for item in items}
        self.word_list.clear()
        for item in items:
            phonetic = f"  {item.phonetic}" if item.phonetic else ""
            list_item = QListWidgetItem(
                f"{item.word}{phonetic}    [{item.level}]\n{item.meaning}"
            )
            list_item.setData(Qt.ItemDataRole.UserRole, item.word_id)
            self.word_list.addItem(list_item)
            row = PronunciationListRow(
                item.word,
                item.phonetic,
                item.meaning,
                self.pronunciation_player,
                self.word_list,
                level=item.level,
            )
            self.word_list.setItemWidget(list_item, row)
            row.bind_to_item(list_item)
        self.count_label.setText(f"{len(items)} 个结果")
        self.status_label.setText(
            "双击词条或选择后查看词卡。" if items else "没有找到匹配的本地词汇。"
        )

    def open_selected(self) -> None:
        if self.worker is not None or self.on_open_word is None:
            return
        current = self.word_list.currentItem()
        if current is None:
            return
        word_id = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(word_id, int):
            return
        result = self._results.get(word_id)
        if result is not None:
            self.on_open_word(result.reference)

    def _item_double_clicked(self, _item: QListWidgetItem) -> None:
        self.open_selected()

    def _selection_changed(self, current, _previous) -> None:
        self.detail_button.setEnabled(
            current is not None
            and self.worker is None
            and self.on_open_word is not None
        )

    def _clear_results(self) -> None:
        self._results.clear()
        self.word_list.clear()
        self.count_label.setText("输入英文单词开始查找")
        self.detail_button.setEnabled(False)

    def _set_busy(self, busy: bool) -> None:
        self.search_input.setEnabled(not busy)
        self.search_button.setEnabled(not busy)
        self.detail_button.setEnabled(False)

    def _task_failed(self, message: str) -> None:
        logger.error("Vocabulary lookup failed: %s", message)
        self._clear_results()
        self.status_label.setText("暂时无法读取本地词库，请稍后重试。")

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.worker_action = None
        self._set_busy(False)
        self._selection_changed(self.word_list.currentItem(), None)
        if self._pending_query is not None:
            pending = self._pending_query
            self._pending_query = None
            self.search_input.setText(pending)
            self.search()
