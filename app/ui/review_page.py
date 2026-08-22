"""Keyboard-friendly vocabulary review screen."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.domain.fsrs_scheduler import Rating
from app.services.review_service import (
    ExtraStudyResult,
    ReviewItem,
    ReviewService,
    ReviewSubmission,
    ReviewUndoResult,
)
from app.services.wordbook_service import FavoriteUpdate, WordbookService
from app.ui.chat_page import ChatContext, ChatPanel, ChatService
from app.ui.widgets.async_worker import AsyncWorker
from app.ui.widgets.review_card import ReviewCardWidget

logger = logging.getLogger(__name__)

RATING_SHORTCUT_GUARD_SECONDS = 0.45


class ReviewPage(QWidget):
    def __init__(
        self,
        service: ReviewService,
        on_reviewed: Callable[[], object] | None = None,
        on_session_state_changed: Callable[[bool], None] | None = None,
        assistant_service: ChatService | None = None,
        wordbook_service: WordbookService | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.on_reviewed = on_reviewed
        self.on_session_state_changed = on_session_state_changed
        self.wordbook_service = wordbook_service
        self.queue: list[ReviewItem] = []
        self.current: ReviewItem | None = None
        self.worker: AsyncWorker | None = None
        self.worker_action: str | None = None
        self._load_after_worker = False
        self.selected_answer = ""
        self.choice_correct: bool | None = None
        self.used_hint = False
        self.started_at = time.monotonic()
        self._rating_shortcuts_ready_at = float("inf")
        self._session_completed = 0
        self._session_loaded = 0
        self._pending_review_item: ReviewItem | None = None
        self._last_reviewed_item: ReviewItem | None = None
        self._last_submission: ReviewSubmission | None = None

        workspace = QHBoxLayout(self)
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)
        learning_area = QWidget()
        outer = QVBoxLayout(learning_area)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(18)
        heading = QHBoxLayout()
        title = QLabel("单词复习")
        title.setObjectName("PageTitle")
        self.progress = QLabel("")
        self.progress.setStyleSheet("color: #64748b;")
        heading.addWidget(title)
        heading.addStretch()
        self.assistant_toggle: QPushButton | None = None
        if assistant_service is not None:
            self.assistant_toggle = QPushButton("隐藏 AI 助手")
            self.assistant_toggle.clicked.connect(self.toggle_assistant)
            heading.addWidget(self.assistant_toggle)
        heading.addWidget(self.progress)
        outer.addLayout(heading)

        card = ReviewCardWidget(
            on_reveal=self.reveal_answer,
            on_unlock=self.unlock_extra_study,
            on_undo=self.undo_last_review,
            on_favorite=self.toggle_favorite,
            on_choice=self.select_meaning,
            on_rating=self.submit,
        )
        self.word_label = card.word_label
        self.phase_label = card.phase_label
        self.phonetic_label = card.phonetic_label
        self.favorite_button = card.favorite_button
        self.answer_label = card.answer_label
        self.example_label = card.example_label
        self.example_translation_label = card.example_translation_label
        self.choice_widget = card.choice_widget
        self.choice_frame = self.choice_widget
        self.choice_help = self.choice_widget.help_label
        self.choice_buttons = self.choice_widget.buttons
        self.learning_aids_frame = card.learning_aids_frame
        self.collocations_label = card.collocations_label
        self.word_family_label = card.word_family_label
        self._show_learning_aids = card.show_learning_aids
        self._hide_learning_aids = card.hide_learning_aids
        self.reveal_button = card.reveal_button
        self.continue_button = card.continue_button
        self.undo_button = card.undo_button
        self.rating_buttons = card.rating_buttons
        if self.wordbook_service is None:
            self.favorite_button.hide()
        outer.addWidget(card)
        outer.addStretch()

        self.assistant_panel: ChatPanel | None = None
        self.workspace_splitter: QSplitter | None = None
        if assistant_service is None:
            workspace.addWidget(learning_area)
        else:
            self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
            self.workspace_splitter.setChildrenCollapsible(False)
            self.workspace_splitter.addWidget(learning_area)
            self.assistant_panel = ChatPanel(
                assistant_service,
                compact=True,
                context_provider=self._assistant_context,
                on_question_submitted=self._assistant_question_submitted,
            )
            self.assistant_panel.setObjectName("AssistantPanel")
            self.assistant_panel.setMinimumWidth(290)
            self.workspace_splitter.addWidget(self.assistant_panel)
            self.workspace_splitter.setStretchFactor(0, 1)
            self.workspace_splitter.setStretchFactor(1, 0)
            self.workspace_splitter.setSizes([620, 340])
            workspace.addWidget(self.workspace_splitter)

        space_shortcut = QShortcut(
            QKeySequence("Space"), learning_area, self.reveal_answer
        )
        space_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        for index, key in enumerate(("1", "2", "3", "4")):
            shortcut = QShortcut(
                QKeySequence(key),
                learning_area,
                partial(self._handle_number_key, index),
            )
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo_shortcut = QShortcut(
            QKeySequence("Ctrl+Z"), learning_area, self.undo_last_review
        )
        undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._set_ratings_enabled(False)

    def load_queue(self) -> bool:
        return self._start_queue_load(reset_progress=True)

    def _start_queue_load(self, *, reset_progress: bool) -> bool:
        if self.worker is not None:
            return False
        if reset_progress:
            self._session_completed = 0
            self._session_loaded = 0
            self._clear_undo()
        self.queue = []
        self.current = None
        self.phase_label.setText("正在加载")
        self.word_label.setText("正在加载复习任务…")
        self.phonetic_label.clear()
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self.favorite_button.setEnabled(False)
        self._hide_learning_aids()
        self._reset_choice_state()
        self.continue_button.hide()
        self.reveal_button.setEnabled(False)
        self._set_ratings_enabled(False)
        self.progress.clear()
        self.worker_action = "load"
        self.worker = AsyncWorker(self.service.get_due_words, parent=self)
        self.worker.result_ready.connect(self._queue_loaded)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        return True

    def _queue_loaded(self, items: list[ReviewItem]) -> None:
        self.queue = list(items)
        self._session_loaded += len(self.queue)
        if self.queue and self.on_session_state_changed:
            self.on_session_state_changed(True)
        self._show_next()

    def _show_next(self) -> None:
        if not self.queue:
            self.current = None
            if self.on_session_state_changed:
                self.on_session_state_changed(False)
            self.word_label.setText("今日复习已完成")
            self.phonetic_label.setText("做得很好，稍后再回来看看吧。")
            self.answer_label.clear()
            self.example_label.clear()
            self.example_translation_label.clear()
            self.favorite_button.hide()
            self._hide_learning_aids()
            self.choice_frame.hide()
            self.reveal_button.setEnabled(False)
            self.continue_button.setText("继续学习 5 个新词")
            self.continue_button.setEnabled(True)
            self.continue_button.show()
            self._set_ratings_enabled(False)
            self.phase_label.setText("本轮完成")
            if self._session_completed:
                self.progress.setText(f"本轮已完成 {self._session_completed} 个")
            else:
                self.progress.setText("0 个待复习")
            self._refresh_undo_button()
            return
        self.current = self.queue.pop(0)
        self.phase_label.setText("阶段 1/2 · 选择释义")
        self.word_label.setText(self.current.word)
        self.phonetic_label.setText(self.current.phonetic)
        self._refresh_favorite_button()
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self._reset_choice_state()
        self.continue_button.hide()
        self.choice_widget.set_options(self.current.meaning_options)
        self.reveal_button.setEnabled(True)
        self.reveal_button.setText("想不起来，显示释义  Space")
        self.reveal_button.show()
        self._set_ratings_enabled(False)
        current_number = self._session_completed + 1
        known_total = max(current_number, self._session_loaded)
        self.progress.setText(
            f"本轮 {current_number}/{known_total} · 本批剩余 {len(self.queue) + 1}"
        )
        self.started_at = time.monotonic()
        self._rating_shortcuts_ready_at = float("inf")
        self._refresh_undo_button()

    def reveal_answer(self) -> None:
        if (
            self.current is None
            or self.choice_correct is not None
            or self._assistant_has_focus()
        ):
            return
        self.used_hint = True
        self.selected_answer = ""
        self.choice_correct = None
        self.answer_label.setText(self.current.meaning)
        self.example_label.setText(self.current.example)
        self.example_translation_label.setText(self.current.example_translation)
        self._show_learning_aids(
            self.current.collocations,
            self.current.word_family,
        )
        self.choice_widget.disable_and_highlight()
        self.choice_widget.hide()
        self.reveal_button.hide()
        self._set_ratings_enabled(True)
        self._rating_shortcuts_ready_at = (
            time.monotonic() + RATING_SHORTCUT_GUARD_SECONDS
        )
        self.phase_label.setText("阶段 2/2 · 评价回忆难度")

    def select_meaning(self, index: int) -> None:
        if self.current is None:
            return
        option = self.choice_widget.option(index)
        if option is None:
            return
        self.selected_answer = option.meaning
        self.choice_correct = option.is_correct
        self.choice_widget.disable_and_highlight(selected_index=index)
        self.choice_widget.hide()
        if self.choice_correct:
            self.choice_help.setText("回答正确，请按真实回忆难度评分。")
            self.answer_label.setText(f"回答正确\n{self.current.meaning}")
        else:
            self.choice_help.setText("回答错误，本题将按 Again 记录。")
            self.answer_label.setText(f"回答错误\n正确释义：{self.current.meaning}")
        self.example_label.setText(self.current.example)
        self.example_translation_label.setText(self.current.example_translation)
        self._show_learning_aids(
            self.current.collocations,
            self.current.word_family,
        )
        self.reveal_button.hide()
        self._set_ratings_enabled(True)
        self._rating_shortcuts_ready_at = (
            time.monotonic() + RATING_SHORTCUT_GUARD_SECONDS
        )
        self.phase_label.setText("阶段 2/2 · 评价回忆难度")

    def submit(self, rating: Rating) -> None:
        if (
            self.worker is not None
            or self.current is None
            or not self.rating_buttons[rating].isEnabled()
        ):
            return
        response_ms = int((time.monotonic() - self.started_at) * 1000)
        self._pending_review_item = self.current
        self._set_ratings_enabled(False)
        self.undo_button.setEnabled(False)
        self.phase_label.setText("正在保存评分…")
        self.worker_action = "submit"
        self.worker = AsyncWorker(
            partial(
                self.service.submit_review,
                self.current.word_id,
                rating,
                response_ms,
                question_type=self._question_type(),
                user_answer=self.selected_answer,
            ),
            parent=self,
        )
        self.worker.result_ready.connect(self._review_saved)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def toggle_favorite(self) -> None:
        if (
            self.worker is not None
            or self.current is None
            or self.wordbook_service is None
        ):
            return
        self.favorite_button.setEnabled(False)
        self.worker_action = "favorite"
        self.worker = AsyncWorker(
            self.wordbook_service.set_favorite,
            self.current.word_id,
            not self.current.is_favorite,
            parent=self,
        )
        self.worker.result_ready.connect(self._favorite_updated)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _favorite_updated(self, result: FavoriteUpdate) -> None:
        if self.current is None or self.current.word_id != result.word_id:
            logger.error("Favorite result does not match the current review card")
            return
        self.current = replace(self.current, is_favorite=result.is_favorite)
        self._refresh_favorite_button()

    def unlock_extra_study(self) -> None:
        if self.worker is not None or self.current is not None:
            return
        self.continue_button.setEnabled(False)
        self.continue_button.setText("正在准备新词…")
        if self.on_session_state_changed:
            self.on_session_state_changed(True)
        self.worker_action = "unlock"
        self.worker = AsyncWorker(self.service.unlock_extra_words, 5, parent=self)
        self.worker.result_ready.connect(self._extra_words_unlocked)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _extra_words_unlocked(self, result: ExtraStudyResult) -> None:
        if result.due_count > 0:
            self.word_label.setText("发现新的到期复习任务")
            self.phonetic_label.setText("优先完成到期任务后再继续学习新词。")
            self.continue_button.hide()
            self._load_after_worker = True
            return
        if result.unlocked_count == 0:
            self.word_label.setText("当前等级的词汇已经全部加入学习计划")
            self.phonetic_label.setText("可以切换等级，或稍后复习已经学过的词。")
            self.continue_button.setText("没有更多新词")
            if self.on_session_state_changed:
                self.on_session_state_changed(False)
            return
        self.word_label.setText(f"已加入 {result.unlocked_count} 个新词")
        self.phonetic_label.setText("正在开始加练…")
        self.continue_button.hide()
        self._load_after_worker = True

    def _review_saved(self, submission: ReviewSubmission) -> None:
        if self._pending_review_item is None:
            logger.error("Saved review has no pending UI item")
            return
        self._last_reviewed_item = self._pending_review_item
        self._last_submission = submission
        self._pending_review_item = None
        self._session_completed += 1
        if self.on_reviewed:
            self.on_reviewed()
        if self.queue:
            self._show_next()
        else:
            # get_due_words is intentionally capped. After one batch finishes,
            # query again instead of incorrectly claiming that all work is done.
            self.current = None
            self.word_label.setText("正在检查剩余复习任务…")
            self.phonetic_label.clear()
            self.answer_label.clear()
            self.example_label.clear()
            self.example_translation_label.clear()
            self.favorite_button.hide()
            self._hide_learning_aids()
            self.choice_frame.hide()
            self.reveal_button.setEnabled(False)
            self.progress.clear()
            self.phase_label.setText("正在检查剩余任务…")
            self._load_after_worker = True

    def undo_last_review(self) -> None:
        if (
            self.worker is not None
            or self._last_submission is None
            or self._last_reviewed_item is None
        ):
            return
        self._set_ratings_enabled(False)
        self.continue_button.setEnabled(False)
        self.undo_button.setEnabled(False)
        self.phase_label.setText("正在撤销上一条评分…")
        self.worker_action = "undo"
        self.worker = AsyncWorker(
            self.service.undo_review,
            self._last_submission.review_log_id,
            parent=self,
        )
        self.worker.result_ready.connect(self._review_undone)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _review_undone(self, result: ReviewUndoResult) -> None:
        if (
            self._last_submission is None
            or self._last_reviewed_item is None
            or result.review_log_id != self._last_submission.review_log_id
        ):
            logger.error("Undo result does not match the latest review")
            return
        if self.current is not None:
            self.queue.insert(0, self.current)
        self.queue.insert(0, self._last_reviewed_item)
        self.current = None
        self._session_completed = max(0, self._session_completed - 1)
        self._clear_undo()
        if self.on_reviewed:
            self.on_reviewed()
        if self.on_session_state_changed:
            self.on_session_state_changed(True)
        self._show_next()

    def _task_failed(self, message: str) -> None:
        if self.worker_action == "favorite":
            logger.error("Could not update favorite: %s", message)
            self._refresh_favorite_button()
            self._show_error("暂时无法更新收藏，请稍后重试。")
            return
        if self.worker_action == "submit":
            logger.error("Review submission failed: %s", message)
            self._pending_review_item = None
            self._set_ratings_enabled(self.current is not None)
            self.phase_label.setText("阶段 2/2 · 评价回忆难度")
            self._refresh_undo_button()
            self._show_error("本次记录未保存，请稍后重试。")
            return
        if self.worker_action == "undo":
            logger.error("Could not undo review: %s", message)
            if self.current is None:
                self.continue_button.setEnabled(True)
                self.phase_label.setText("本轮完成")
            else:
                self._set_ratings_enabled(
                    self.choice_correct is not None
                    or not self.reveal_button.isVisible()
                )
                self.phase_label.setText(
                    "阶段 2/2 · 评价回忆难度"
                    if self.choice_correct is not None
                    or not self.reveal_button.isVisible()
                    else "阶段 1/2 · 选择释义"
                )
            self._refresh_undo_button()
            self._show_error("无法撤销上一条评分，学习记录未被更改。")
            return
        if self.worker_action == "unlock":
            logger.error("Could not unlock extra study: %s", message)
            self.continue_button.setText("继续学习 5 个新词")
            self.continue_button.setEnabled(True)
            if self.on_session_state_changed:
                self.on_session_state_changed(False)
            self._show_error("暂时无法准备加练词汇，请稍后重试。")
            return
        logger.error("Could not load review queue: %s", message)
        self.queue = []
        self.current = None
        if self.on_session_state_changed:
            self.on_session_state_changed(False)
        self.word_label.setText("暂时无法加载复习任务")
        self.phonetic_label.clear()
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self.favorite_button.hide()
        self._hide_learning_aids()
        self.reveal_button.setEnabled(False)
        self.continue_button.hide()
        self._set_ratings_enabled(False)
        self.progress.clear()
        self.phase_label.setText("加载失败")
        self._refresh_undo_button()
        self._show_error("暂时无法读取复习任务，请稍后重试。")

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.worker_action = None
        if self._load_after_worker:
            self._load_after_worker = False
            self._start_queue_load(reset_progress=False)
            return
        self._refresh_favorite_button()
        self._refresh_undo_button()

    def _set_ratings_enabled(self, enabled: bool) -> None:
        for rating, button in self.rating_buttons.items():
            button.setEnabled(
                enabled and (self.choice_correct is not False or rating is Rating.AGAIN)
            )

    def _handle_number_key(self, index: int) -> None:
        if self._assistant_has_focus():
            return
        if self.choice_widget.choose_with_number(index):
            return
        if time.monotonic() < self._rating_shortcuts_ready_at:
            return
        self.submit(tuple(Rating)[index])

    def _reset_choice_state(self) -> None:
        self.selected_answer = ""
        self.choice_correct = None
        self.used_hint = False
        self._rating_shortcuts_ready_at = float("inf")
        self._hide_learning_aids()
        self.choice_widget.reset()

    def _refresh_favorite_button(self) -> None:
        if self.wordbook_service is None or self.current is None:
            self.favorite_button.hide()
            return
        self.favorite_button.setText(
            "★ 已收藏" if self.current.is_favorite else "☆ 收藏"
        )
        self.favorite_button.setEnabled(self.worker is None)
        self.favorite_button.show()

    def _clear_undo(self) -> None:
        self._last_reviewed_item = None
        self._last_submission = None
        self.undo_button.hide()

    def _refresh_undo_button(self) -> None:
        available = (
            self._last_reviewed_item is not None and self._last_submission is not None
        )
        self.undo_button.setVisible(available)
        self.undo_button.setEnabled(available and self.worker is None)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "CET-Agent", message)

    def _question_type(self) -> str:
        if not self.selected_answer:
            return "meaning_recall_with_hint"
        outcome = "correct" if self.choice_correct else "wrong"
        hint_suffix = "_with_ai_hint" if self.used_hint else ""
        return f"meaning_choice_{outcome}{hint_suffix}"

    def toggle_assistant(self) -> None:
        if self.assistant_panel is None or self.assistant_toggle is None:
            return
        show_panel = self.assistant_panel.isHidden()
        self.assistant_panel.setVisible(show_panel)
        self.assistant_toggle.setText("隐藏 AI 助手" if show_panel else "显示 AI 助手")
        if show_panel and self.workspace_splitter is not None:
            self.workspace_splitter.setSizes([620, 340])

    def _assistant_context(self) -> ChatContext | None:
        if self.current is None:
            return None
        return ChatContext(
            label=self.current.word,
            content=(
                f"word={self.current.word}\n"
                f"phonetic={self.current.phonetic}\n"
                f"meaning={self.current.meaning}\n"
                f"example={self.current.example}"
            ),
        )

    def _assistant_question_submitted(self) -> None:
        if self.current is None:
            return
        self.used_hint = True
        if self.choice_correct is None:
            self.choice_help.setText("已使用 AI 提示，请结合实际回忆情况评分。")

    def _assistant_has_focus(self) -> bool:
        if self.assistant_panel is None:
            return False
        focus = QApplication.focusWidget()
        return focus is not None and (
            focus is self.assistant_panel or self.assistant_panel.isAncestorOf(focus)
        )
