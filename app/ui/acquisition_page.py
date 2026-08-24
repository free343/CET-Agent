"""Three-stage new-word acquisition workspace."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.services.acquisition_service import (
    AcquisitionService,
    AcquisitionSubmission,
)
from app.services.lexical_fact_view import LinkedWordReference
from app.services.mastery_service import MasteryService, MasteryUpdate
from app.services.review_item_view import ReviewItem
from app.services.wordbook_service import FavoriteUpdate, WordbookService
from app.ui.chat_page import (
    STUDY_ASSISTANT_MIN_WIDTH,
    STUDY_WORKSPACE_INITIAL_SIZES,
    ChatContext,
    ChatPanel,
    ChatService,
)
from app.ui.session_summary import format_acquisition_summary
from app.ui.widgets.async_worker import AsyncWorker
from app.ui.widgets.review_card import ReviewCardWidget

logger = logging.getLogger(__name__)


class AcquisitionPage(QWidget):
    """Round-robin new-word learning; formal FSRS remains in ReviewPage."""

    def __init__(
        self,
        service: AcquisitionService,
        *,
        on_changed: Callable[[], object] | None = None,
        on_session_state_changed: Callable[[bool], None] | None = None,
        assistant_service: ChatService | None = None,
        wordbook_service: WordbookService | None = None,
        mastery_service: MasteryService | None = None,
        on_linked_word: Callable[[LinkedWordReference], None] | None = None,
        pronunciation_player: object | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.group_size = service.group_size
        self.extra_new_word_count = service.extra_study_limit
        self.on_changed = on_changed
        self.on_session_state_changed = on_session_state_changed
        self.wordbook_service = wordbook_service
        self.mastery_service = mastery_service
        self.queue: list[ReviewItem] = []
        self.current: ReviewItem | None = None
        self.worker: AsyncWorker | None = None
        self.worker_action: str | None = None
        self._load_after_worker = False
        self._check_completion_after_worker = False
        self._released_group_available = False
        self._completion_check_failed = False
        self._answer_revealed = False
        self._content_error = False
        self._pending_item: ReviewItem | None = None
        self._next_item: ReviewItem | None = None
        self._session_completed = 0
        self._session_loaded = 0
        self._session_attempts = 0
        self._session_mistakes = 0
        self._session_stage_attempts: dict[int, int] = {}
        self._session_stage_mistakes: dict[int, int] = {}
        self._session_first_review_at: datetime | None = None
        self.started_at = time.monotonic()

        workspace = QHBoxLayout(self)
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)
        learning_area = QWidget()
        outer = QVBoxLayout(learning_area)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(18)
        heading = QHBoxLayout()
        self.title = QLabel("学习新词")
        self.title.setObjectName("PageTitle")
        self.progress = QLabel("")
        self.progress.setStyleSheet("color: #64748b;")
        heading.addWidget(self.title)
        heading.addStretch()
        heading.addWidget(self.progress)
        outer.addLayout(heading)

        self.card = ReviewCardWidget(
            on_reveal=self._advance_after_feedback,
            on_unlock=self.continue_learning,
            on_undo=lambda: None,
            on_favorite=self.toggle_favorite,
            on_mastered=self.toggle_mastered if mastery_service is not None else None,
            on_choice=self.select_meaning,
            on_rating=lambda _rating: None,
            on_linked_word=on_linked_word,
            pronunciation_player=pronunciation_player,
        )
        self.word_label = self.card.word_label
        self.phonetic_label = self.card.phonetic_label
        self.phase_label = self.card.phase_label
        self.favorite_button = self.card.favorite_button
        self.mastered_button = self.card.mastered_button
        self.answer_label = self.card.answer_label
        self.example_label = self.card.example_label
        self.example_translation_label = self.card.example_translation_label
        self.choice_widget = self.card.choice_widget
        self.english_choice_widget = self.card.english_choice_widget
        self.spelling_panel = self.card.spelling_panel
        self.spelling_input = self.card.spelling_input
        self.spelling_submit_button = self.card.spelling_submit_button
        self.self_confirm_button = self.card.self_confirm_button
        self.reveal_button = self.card.reveal_button
        self.continue_button = self.card.continue_button
        self.continue_button.setText(f"继续学习 {self.extra_new_word_count} 个新词")
        self.rating_buttons = self.card.rating_buttons
        self.undo_button = self.card.undo_button
        self._hide_formal_controls()
        self.english_choice_widget.option_selected.connect(self.select_cloze)
        self.spelling_submit_button.clicked.connect(self.submit_spelling)
        self.self_confirm_button.clicked.connect(self.confirm_spelling)
        self.spelling_input.returnPressed.connect(self.submit_spelling)
        if self.wordbook_service is None:
            self.favorite_button.hide()
        if self.mastery_service is None:
            self.mastered_button.hide()
        outer.addWidget(self.card)
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
            )
            self.assistant_panel.setObjectName("AssistantPanel")
            self.assistant_panel.setMinimumWidth(STUDY_ASSISTANT_MIN_WIDTH)
            self.workspace_splitter.addWidget(self.assistant_panel)
            self.workspace_splitter.setStretchFactor(0, 1)
            self.workspace_splitter.setStretchFactor(1, 0)
            self.workspace_splitter.setSizes(list(STUDY_WORKSPACE_INITIAL_SIZES))
            workspace.addWidget(self.workspace_splitter)

        QShortcut(
            QKeySequence("Space"),
            learning_area,
            self._advance_after_feedback,
        ).setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        for index, key in enumerate(("1", "2", "3", "4")):
            shortcut = QShortcut(
                QKeySequence(key),
                learning_area,
                partial(self._handle_number_key, index),
            )
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def load_queue(self, *, reset_progress: bool = True) -> bool:
        if self.worker is not None:
            return False
        if reset_progress:
            self._session_completed = 0
            self._session_loaded = 0
            self._session_attempts = 0
            self._session_mistakes = 0
            self._session_stage_attempts.clear()
            self._session_stage_mistakes.clear()
            self._session_first_review_at = None
        self._released_group_available = False
        self._completion_check_failed = False
        self.queue = []
        self.current = None
        self._answer_revealed = False
        self._sync_assistant_context()
        self._show_loading("正在加载待学新词…")
        self.worker_action = "load"
        self.worker = AsyncWorker(
            self.service.get_group,
            parent=self,
        )
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
            self._answer_revealed = False
            self._sync_assistant_context()
            if self.on_session_state_changed:
                self.on_session_state_changed(False)
            self._show_completion()
            return
        self.current = self.queue.pop(0)
        self._answer_revealed = False
        self._sync_assistant_context()
        self._next_item = None
        self._reset_card()
        self._refresh_favorite_button()
        self._refresh_mastered_button()
        self.started_at = time.monotonic()
        level = self.current.proficiency_level
        current_number = self._session_completed + 1
        known_total = max(current_number, self._session_loaded)
        self.progress.setText(
            f"本轮 {current_number}/{known_total} · 本组剩余 {len(self.queue) + 1}"
        )
        if level == 0:
            self.phase_label.setText("熟练度 0/3 · 选择中文释义")
            self.word_label.setText(self.current.word)
            self.phonetic_label.setText(self.current.phonetic)
            self.card.set_pronunciation_word(self.current.word)
            if not self.choice_widget.set_options(self.current.meaning_options):
                self._show_content_error("当前单词暂时无法生成四个可靠释义选项。")
            else:
                self._set_stage_enabled(True)
            return
        if level == 1:
            self.phase_label.setText("熟练度 1/3 · 例句挖空选择")
            self.answer_label.setText(self.current.cloze_example)
            self.example_translation_label.setText(self.current.example_translation)
            if not self.english_choice_widget.set_options(self.current.cloze_options):
                self._show_content_error("当前例句暂时无法生成四个可靠英语选项。")
            else:
                self._set_stage_enabled(True)
            return
        self.phase_label.setText("熟练度 2/3 · 拼写单词")
        self.answer_label.setText(self.current.meaning)
        self.spelling_panel.show()
        self._set_stage_enabled(True)
        self.spelling_input.setFocus()

    def select_meaning(self, index: int) -> None:
        if self.current is None or self.current.proficiency_level != 0:
            return
        option = self.choice_widget.option(index)
        if option is None:
            return
        self.choice_widget.disable_and_highlight(index)
        self._start_attempt(selected_word_id=option.word_id)

    def select_cloze(self, index: int) -> None:
        if self.current is None or self.current.proficiency_level != 1:
            return
        option = self.english_choice_widget.option(index)
        if option is None:
            return
        self.english_choice_widget.disable_and_highlight(index)
        self._start_attempt(selected_word_id=option.word_id)

    def submit_spelling(self) -> None:
        if self.current is None or self.current.proficiency_level != 2:
            return
        answer = self.spelling_input.text()
        if not answer.strip():
            return
        self._start_attempt(spelling_answer=answer)

    def confirm_spelling(self) -> None:
        if self.current is None or self.current.proficiency_level != 2:
            return
        self._start_attempt(self_confirmed=True)

    def _start_attempt(
        self,
        *,
        selected_word_id: int | None = None,
        spelling_answer: str = "",
        self_confirmed: bool = False,
    ) -> None:
        if self.worker is not None or self.current is None:
            return
        self._pending_item = self.current
        self._set_stage_enabled(False)
        self.phase_label.setText("正在保存本次学习结果…")
        self.worker_action = "attempt"
        self.worker = AsyncWorker(
            partial(
                self.service.record_attempt,
                self.current.word_id,
                expected_level=self.current.proficiency_level,
                selected_word_id=selected_word_id,
                spelling_answer=spelling_answer,
                self_confirmed=self_confirmed,
                response_time_ms=int((time.monotonic() - self.started_at) * 1000),
            ),
            parent=self,
        )
        self.worker.result_ready.connect(self._attempt_saved)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _attempt_saved(self, result: AcquisitionSubmission) -> None:
        if self._pending_item is None or result.word_id != self._pending_item.word_id:
            logger.error("Acquisition result does not match pending card")
            return
        self._next_item = result.next_item
        if not result.completed and self._next_item is None:
            # A concurrent mastery action can remove the projection after the
            # attempt transaction commits.  Do not strand the group or reopen
            # an answerless card; reload the persisted queue after this worker
            # finishes and let the service apply the authoritative exclusion.
            logger.warning(
                "Acquisition projection disappeared after attempt word_id=%s",
                result.word_id,
            )
            self._pending_item = None
            self.current = None
            self.queue = []
            self._sync_assistant_context()
            self._load_after_worker = True
            return
        self._session_attempts += 1
        self._session_stage_attempts[result.level_before] = (
            self._session_stage_attempts.get(result.level_before, 0) + 1
        )
        if not result.is_correct:
            self._session_mistakes += 1
            self._session_stage_mistakes[result.level_before] = (
                self._session_stage_mistakes.get(result.level_before, 0) + 1
            )
        if result.completed:
            self._session_completed += 1
            if result.first_review_at is not None and (
                self._session_first_review_at is None
                or result.first_review_at < self._session_first_review_at
            ):
                self._session_first_review_at = result.first_review_at
        if self.on_changed:
            self.on_changed()
        self._answer_revealed = True
        self._render_feedback(result)

    def _render_feedback(self, result: AcquisitionSubmission) -> None:
        if self.current is None:
            return
        self._sync_assistant_context()
        current = self.current
        self.choice_widget.hide()
        self.english_choice_widget.hide()
        self.spelling_panel.hide()
        self.word_label.setText(current.word)
        self.phonetic_label.setText(current.phonetic)
        self.card.set_pronunciation_word(current.word)
        self.answer_label.setText(
            ("回答正确" if result.is_correct else "回答错误")
            + f"\n中文释义：{current.meaning}"
        )
        self.example_label.setText(current.example)
        self.example_translation_label.setText(current.example_translation)
        self.card.show_learning_aids(
            current.collocations,
            current.word_family,
            has_learning_aid=current.has_learning_aid,
            lexical_sections=(
                current.lexical_sections if current.lexical_facts_available else None
            ),
        )
        self.reveal_button.setText("继续学习  Space")
        self.reveal_button.show()
        self.reveal_button.setEnabled(False)
        self.phase_label.setText(
            f"{'已完成本阶段' if result.is_correct else '本次未答对'} · "
            f"熟练度 {result.level_after}/3"
        )
        if result.completed:
            self.answer_label.setText("这个单词已完成新词学习")

    def _advance_after_feedback(self) -> None:
        if self._content_error:
            self._content_error = False
            self.load_queue(reset_progress=False)
            return
        if self.worker is not None or not self._answer_revealed:
            return
        if self._next_item is not None:
            self.queue.append(self._next_item)
        self._pending_item = None
        self._next_item = None
        self.current = None
        if self.queue:
            self._show_next()
        else:
            self._sync_assistant_context()
            self._check_group_completion()

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
            return
        self.current = replace(self.current, is_favorite=result.is_favorite)
        self._refresh_favorite_button()

    def toggle_mastered(self) -> None:
        if (
            self.worker is not None
            or self.current is None
            or self.mastery_service is None
        ):
            return
        self.worker_action = "mastered"
        self.favorite_button.setEnabled(False)
        self.mastered_button.setEnabled(False)
        self.worker = AsyncWorker(
            self.mastery_service.set_mastered,
            self.current.word_id,
            True,
            parent=self,
        )
        self.worker.result_ready.connect(self._mastered_updated)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _mastered_updated(self, result: MasteryUpdate) -> None:
        if self.current is None or self.current.word_id != result.word_id:
            return
        self.current = None
        if self.on_changed:
            self.on_changed()
        if self.queue:
            self._show_next()
        else:
            self._sync_assistant_context()
            self._check_completion_after_worker = True

    def continue_learning(self) -> None:
        """Start the next released group or explicitly unlock the configured pack."""

        if self.worker is not None or self.current is not None:
            return
        if self._completion_check_failed:
            self._check_group_completion()
            return
        if self._released_group_available:
            self._released_group_available = False
            self.load_queue(reset_progress=False)
            return
        self.unlock_extra_words()

    def _check_group_completion(self) -> None:
        if self.worker is not None or self.current is not None:
            return
        self._released_group_available = False
        self._completion_check_failed = False
        self._show_completion("正在检查是否还有已释放的新词…")
        self.worker_action = "remaining"
        self.worker = AsyncWorker(
            self.service.remaining_count,
            parent=self,
        )
        self.worker.result_ready.connect(self._group_remaining_checked)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _group_remaining_checked(self, remaining_count: int) -> None:
        if remaining_count > 0:
            self._released_group_available = True
            self._show_completion("本组新词已经完成，可以开始下一组。")
        else:
            self._show_completion()

    def unlock_extra_words(self) -> None:
        if self.worker is not None or self.current is not None:
            return
        self.continue_button.setEnabled(False)
        self.continue_button.setText("正在准备新词…")
        self.worker_action = "unlock"
        self.worker = AsyncWorker(
            self.service.unlock_extra_words,
            parent=self,
        )
        self.worker.result_ready.connect(self._extra_words_unlocked)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _extra_words_unlocked(self, result) -> None:
        if result.due_count > 0:
            self._show_completion("请先完成已到期复习，再继续释放新词。")
            return
        if result.unlocked_count == 0:
            self._show_completion("当前等级没有更多可释放的新词。")
            return
        self._load_after_worker = True

    def _show_completion(
        self, detail: str = "本组单词已经完成，可以继续学习下一组。"
    ) -> None:
        self.word_label.setText("本组新词已完成")
        self.phonetic_label.setText(f"{detail} {self._session_summary()}")
        self.card.clear_pronunciation()
        self.phase_label.setText("本轮完成")
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self.favorite_button.hide()
        self.mastered_button.hide()
        self.choice_widget.hide()
        self.english_choice_widget.hide()
        self.spelling_panel.hide()
        self.card.hide_learning_aids()
        self.reveal_button.hide()
        self.continue_button.setText(
            "开始下一组新词"
            if self._released_group_available
            else f"继续学习 {self.extra_new_word_count} 个新词"
        )
        self.continue_button.setEnabled(self.worker is None)
        self.continue_button.show()
        self.progress.setText(f"本轮完成 {self._session_completed} 个")

    def _session_summary(self) -> str:
        return format_acquisition_summary(
            self._session_attempts,
            self._session_mistakes,
            self._session_completed,
            self._session_stage_attempts,
            self._session_stage_mistakes,
            self._session_first_review_at,
        )

    def _show_loading(self, text: str) -> None:
        self._reset_card()
        self.word_label.setText(text)
        self.phase_label.setText("正在加载")
        self.progress.clear()

    def _show_content_error(self, message: str) -> None:
        self._content_error = True
        self.phase_label.setText("学习内容暂不可用")
        self._set_stage_enabled(False)
        self.answer_label.setText(message)
        self.reveal_button.setText("重试加载当前词")
        self.reveal_button.setEnabled(self.worker is None)
        self.reveal_button.show()

    def _reset_card(self) -> None:
        self._content_error = False
        self._hide_formal_controls()
        self.word_label.clear()
        self.phonetic_label.clear()
        self.card.clear_pronunciation()
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self.choice_widget.reset()
        self.english_choice_widget.reset()
        self.spelling_input.clear()
        self.card.hide_learning_aids()
        self.reveal_button.hide()
        self.continue_button.hide()

    def _hide_formal_controls(self) -> None:
        for button in self.rating_buttons.values():
            button.hide()
        self.undo_button.hide()
        self.reveal_button.hide()
        self.continue_button.hide()

    def _set_stage_enabled(self, enabled: bool) -> None:
        for button in self.choice_widget.buttons:
            button.setEnabled(enabled and self.current is not None)
        for button in self.english_choice_widget.buttons:
            button.setEnabled(enabled and self.current is not None)
        self.spelling_input.setEnabled(enabled and self.current is not None)
        self.spelling_submit_button.setEnabled(enabled and self.current is not None)
        self.self_confirm_button.setEnabled(enabled and self.current is not None)
        if self.current is None:
            self.card.clear_pronunciation()
        elif self.current.proficiency_level == 0:
            self.card.set_pronunciation_word(self.current.word, enabled=enabled)
        else:
            self.card.clear_pronunciation()
        self._refresh_favorite_button()
        self._refresh_mastered_button()

    def _refresh_favorite_button(self) -> None:
        if self.wordbook_service is None or self.current is None:
            self.favorite_button.hide()
            return
        self.favorite_button.setText(
            "★ 已收藏" if self.current.is_favorite else "☆ 收藏"
        )
        self.favorite_button.setEnabled(self.worker is None)
        self.favorite_button.show()

    def _refresh_mastered_button(self) -> None:
        if self.mastery_service is None or self.current is None:
            self.mastered_button.hide()
            return
        self.mastered_button.setText("✓ 完全掌握")
        self.mastered_button.setEnabled(self.worker is None)
        self.mastered_button.show()

    def _handle_number_key(self, index: int) -> None:
        if self._assistant_has_focus():
            return
        if self.current is None or self.worker is not None:
            return
        if self.current.proficiency_level == 0:
            self.choice_widget.choose_with_number(index)
        elif self.current.proficiency_level == 1:
            self.english_choice_widget.choose_with_number(index)

    def _assistant_context(self) -> ChatContext | None:
        if self.current is None or not self._answer_revealed:
            return None
        return ChatContext(
            label=self.current.word,
            content=(
                f"word={self.current.word}\n"
                f"phonetic={self.current.phonetic}\n"
                f"meaning={self.current.meaning}\n"
                f"example={self.current.example}\n"
                f"collocations={' ; '.join(self.current.collocations)}\n"
                f"word_family={' ; '.join(self.current.word_family)}\n"
                + "\n".join(
                    f"{section.title}={'; '.join(section.items)}"
                    for section in self.current.lexical_sections
                )
            ),
        )

    def _sync_assistant_context(self) -> None:
        if self.assistant_panel is not None:
            self.assistant_panel.context_changed()

    def _assistant_has_focus(self) -> bool:
        if self.assistant_panel is None:
            return False
        focus = QApplication.focusWidget()
        return focus is not None and (
            focus is self.assistant_panel or self.assistant_panel.isAncestorOf(focus)
        )

    def _task_failed(self, message: str) -> None:
        action = self.worker_action
        logger.error(
            "Acquisition page action failed action=%s message=%s", action, message
        )
        if action == "attempt":
            self._pending_item = None
            self._set_stage_enabled(True)
            self.phase_label.setText("请重新完成当前阶段")
            QMessageBox.warning(self, "CET-Agent", "本次学习记录未保存，请稍后重试。")
            return
        if action == "favorite":
            self._refresh_favorite_button()
            QMessageBox.warning(self, "CET-Agent", "收藏操作失败，请稍后重试。")
            return
        if action == "mastered":
            self._refresh_favorite_button()
            self._refresh_mastered_button()
            QMessageBox.warning(self, "CET-Agent", "完全掌握操作失败，请稍后重试。")
            return
        if action == "remaining":
            self._completion_check_failed = True
            self._released_group_available = False
            self._show_completion("暂时无法检查下一组新词，请点击重试。")
            self.continue_button.setText("重试检查")
            return
        self.queue = []
        self.current = None
        self._sync_assistant_context()
        if self.on_session_state_changed:
            self.on_session_state_changed(False)
        self._show_completion("暂时无法读取新词，请稍后重试。")

    def _worker_finished(self) -> None:
        action = self.worker_action
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.worker_action = None
        if action == "attempt" and self._answer_revealed:
            self.reveal_button.setEnabled(True)
        self._refresh_favorite_button()
        self._refresh_mastered_button()
        if (
            action in {"load", "unlock", "remaining"}
            and self.current is None
            and self._load_after_worker is False
        ):
            # Error/empty completion is rendered while the worker is still
            # alive.  Re-enable the retry/continuation action once the worker
            # has actually released the page-owned slot.
            self.continue_button.setEnabled(True)
        if action == "mastered" and self._check_completion_after_worker:
            self._check_completion_after_worker = False
            self._check_group_completion()
            return
        if self._load_after_worker:
            self._load_after_worker = False
            self.load_queue(reset_progress=False)
