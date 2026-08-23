"""Management view for reversible completely-mastered words."""

from __future__ import annotations

import logging

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

from app.services.mastery_service import MasteredWordItem, MasteryService, MasteryUpdate
from app.ui.widgets.async_worker import AsyncWorker

logger = logging.getLogger(__name__)


class MasteredPage(QWidget):
    def __init__(self, service: MasteryService) -> None:
        super().__init__()
        self.service = service
        self.worker: AsyncWorker | None = None
        self.worker_action: str | None = None
        self._refresh_after_worker = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("已掌握单词")
        title.setObjectName("PageTitle")
        self.count_label = QLabel("0 个单词")
        self.count_label.setStyleSheet("color: #64748b;")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.count_label)
        layout.addLayout(heading)

        subtitle = QLabel(
            "这些单词不会出现在新词学习、正式复习或自由复习中；你可以随时恢复学习。"
        )
        subtitle.setStyleSheet("color: #64748b;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.status_label = QLabel("正在加载已掌握单词…")
        self.status_label.setStyleSheet("color: #64748b; padding: 6px 2px;")
        layout.addWidget(self.status_label)
        self.word_list = QListWidget()
        self.word_list.setObjectName("MasteredList")
        self.word_list.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.word_list, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        self.restore_button = QPushButton("恢复学习")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore_selected)
        actions.addWidget(self.restore_button)
        layout.addLayout(actions)

    def refresh(self) -> bool:
        if self.worker is not None:
            self._refresh_after_worker = True
            return False
        self.status_label.setText("正在加载已掌握单词…")
        self.restore_button.setEnabled(False)
        self.worker_action = "load"
        self.worker = AsyncWorker(self.service.list_mastered, parent=self)
        self.worker.result_ready.connect(self._show_items)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        return True

    def _show_items(self, items: list[MasteredWordItem]) -> None:
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
        self.count_label.setText(f"{len(items)} 个单词")
        self.status_label.setText(
            "选择词条后可以恢复学习。" if items else "暂无完全掌握的单词。"
        )

    def restore_selected(self) -> None:
        if self.worker is not None:
            return
        item = self.word_list.currentItem()
        if item is None:
            return
        word_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(word_id, int):
            return
        self.restore_button.setEnabled(False)
        self.worker_action = "restore"
        self.worker = AsyncWorker(
            self.service.set_mastered,
            word_id,
            False,
            parent=self,
        )
        self.worker.result_ready.connect(self._restored)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _restored(self, result: MasteryUpdate) -> None:
        if result.is_mastered:
            logger.error(
                "Restore returned mastered=true for word_id=%s", result.word_id
            )
            return
        self._refresh_after_worker = True

    def _selection_changed(self, current, _previous) -> None:
        self.restore_button.setEnabled(current is not None and self.worker is None)

    def _task_failed(self, message: str) -> None:
        logger.error(
            "Mastered page action failed action=%s message=%s",
            self.worker_action,
            message,
        )
        if self.worker_action == "load":
            self.word_list.clear()
            self.count_label.setText("— 个单词")
            self.restore_button.setEnabled(False)
            self.status_label.setText("暂时无法读取已掌握单词，请稍后重试。")
            return
        self.status_label.setText("暂时无法恢复学习，请稍后重试。")
        QMessageBox.warning(self, "CET-Agent", "恢复学习失败，请稍后重试。")

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
