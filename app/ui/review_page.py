"""Keyboard-friendly vocabulary review screen."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from enum import Enum
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.db.models import LearningAidIssueType
from app.domain.fsrs_scheduler import Rating
from app.services.learning_aid_feedback_service import (
    LearningAidFeedbackService,
    LearningAidFeedbackUpdate,
)
from app.services.mastery_service import MasteryService, MasteryUpdate
from app.services.practice_service import (
    PracticeScope,
    PracticeService,
    PracticeSubmission,
)
from app.services.review_service import (
    ExtraStudyResult,
    ReviewItem,
    ReviewService,
    ReviewSubmission,
    ReviewUndoResult,
)
from app.services.wordbook_service import FavoriteUpdate, WordbookService
from app.ui.chat_page import (
    STUDY_ASSISTANT_MIN_WIDTH,
    STUDY_WORKSPACE_INITIAL_SIZES,
    ChatContext,
    ChatPanel,
    ChatService,
)
from app.ui.widgets.async_worker import AsyncWorker
from app.ui.widgets.review_card import ReviewCardWidget

logger = logging.getLogger(__name__)

RATING_SHORTCUT_GUARD_SECONDS = 0.45
LEARNING_AID_ISSUE_CHOICES: tuple[tuple[str, LearningAidIssueType], ...] = (
    ("例句不自然", LearningAidIssueType.EXAMPLE_UNNATURAL),
    ("例句与释义不匹配", LearningAidIssueType.MEANING_MISMATCH),
    ("中文翻译不准确", LearningAidIssueType.TRANSLATION_INACCURATE),
    ("固定搭配不常用", LearningAidIssueType.COLLOCATION_UNCOMMON),
    ("同族或派生词关系错误", LearningAidIssueType.WORD_FAMILY_INCORRECT),
    ("其他问题", LearningAidIssueType.OTHER),
)


class StudySessionMode(str, Enum):
    """The explicit learning intent behind a shared card workflow."""

    COMBINED = "COMBINED"
    LEARN = "LEARN"
    REVIEW = "REVIEW"
    PRACTICE = "PRACTICE"


PRACTICE_SCOPE_LABELS: tuple[tuple[str, PracticeScope], ...] = (
    ("昨天学过", PracticeScope.YESTERDAY),
    ("最近学习", PracticeScope.RECENT),
    ("历史错词", PracticeScope.WRONG),
    ("收藏单词", PracticeScope.FAVORITES),
)


class ReviewPage(QWidget):
    def __init__(
        self,
        service: ReviewService,
        on_reviewed: Callable[[], object] | None = None,
        on_session_state_changed: Callable[[bool], None] | None = None,
        assistant_service: ChatService | None = None,
        wordbook_service: WordbookService | None = None,
        mastery_service: MasteryService | None = None,
        learning_aid_feedback_service: LearningAidFeedbackService | None = None,
        *,
        session_mode: StudySessionMode | str = StudySessionMode.COMBINED,
        practice_service: PracticeService | None = None,
        practice_scope: PracticeScope | str = PracticeScope.YESTERDAY,
    ) -> None:
        super().__init__()
        self.service = service
        self.session_mode = StudySessionMode(session_mode)
        self.practice_service = practice_service
        self.practice_scope = PracticeScope(practice_scope)
        if (
            self.session_mode is StudySessionMode.PRACTICE
            and self.practice_service is None
        ):
            raise ValueError("Practice mode requires PracticeService")
        self.on_reviewed = on_reviewed
        self.on_session_state_changed = on_session_state_changed
        self.wordbook_service = wordbook_service
        self.mastery_service = mastery_service
        self.learning_aid_feedback_service = learning_aid_feedback_service
        self.queue: list[ReviewItem] = []
        self.current: ReviewItem | None = None
        self.worker: AsyncWorker | None = None
        self.worker_action: str | None = None
        self._load_after_worker = False
        self._reset_progress_after_worker = False
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
        self._learning_intro_active = False
        self._practice_completed_ids: set[int] = set()

        workspace = QHBoxLayout(self)
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)
        learning_area = QWidget()
        outer = QVBoxLayout(learning_area)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(18)
        heading = QHBoxLayout()
        self.title = QLabel(self._page_title())
        self.title.setObjectName("PageTitle")
        self.progress = QLabel("")
        self.progress.setStyleSheet("color: #64748b;")
        heading.addWidget(self.title)
        heading.addStretch()
        self.practice_scope_combo: QComboBox | None = None
        if self.session_mode is StudySessionMode.PRACTICE:
            scope_label = QLabel("练习范围")
            scope_label.setStyleSheet("color: #64748b;")
            heading.addWidget(scope_label)
            self.practice_scope_combo = QComboBox()
            for label, scope in PRACTICE_SCOPE_LABELS:
                self.practice_scope_combo.addItem(label, scope.value)
            selected_index = self.practice_scope_combo.findData(
                self.practice_scope.value
            )
            self.practice_scope_combo.setCurrentIndex(max(0, selected_index))
            self.practice_scope_combo.currentIndexChanged.connect(
                self._practice_scope_changed
            )
            heading.addWidget(self.practice_scope_combo)
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
            on_mastered=self.toggle_mastered if mastery_service is not None else None,
            on_choice=self.select_meaning,
            on_rating=self.submit,
            on_report_learning_aid=self.report_learning_aid_issue,
        )
        self.word_label = card.word_label
        self.phase_label = card.phase_label
        self.phonetic_label = card.phonetic_label
        self.favorite_button = card.favorite_button
        self.mastered_button = card.mastered_button
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
        self.learning_aid_status_label = card.learning_aid_status_label
        self.learning_aid_report_button = card.learning_aid_report_button
        self._show_learning_aids = card.show_learning_aids
        self._hide_learning_aids = card.hide_learning_aids
        self.reveal_button = card.reveal_button
        self.continue_button = card.continue_button
        self.undo_button = card.undo_button
        self.rating_buttons = card.rating_buttons
        if self.session_mode is StudySessionMode.PRACTICE:
            self.rating_buttons[Rating.AGAIN].setText("1  没想起")
            self.rating_buttons[Rating.GOOD].setText("2  想起来")
            self.rating_buttons[Rating.HARD].hide()
            self.rating_buttons[Rating.EASY].hide()
        if self.wordbook_service is None:
            self.favorite_button.hide()
        if self.mastery_service is None:
            self.mastered_button.hide()
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
            self.assistant_panel.setMinimumWidth(STUDY_ASSISTANT_MIN_WIDTH)
            self.workspace_splitter.addWidget(self.assistant_panel)
            self.workspace_splitter.setStretchFactor(0, 1)
            self.workspace_splitter.setStretchFactor(1, 0)
            self.workspace_splitter.setSizes(list(STUDY_WORKSPACE_INITIAL_SIZES))
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
            self._practice_completed_ids.clear()
            self._clear_undo()
        self.queue = []
        self.current = None
        self._learning_intro_active = False
        self._sync_assistant_context()
        self.phase_label.setText("正在加载")
        self.word_label.setText(self._loading_text())
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
        self.worker = AsyncWorker(self._queue_loader(), parent=self)
        self.worker.result_ready.connect(self._queue_loaded)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        return True

    def _queue_loader(self) -> Callable[[], list[ReviewItem]]:
        if self.session_mode is StudySessionMode.LEARN:
            return self.service.get_new_words
        if self.session_mode is StudySessionMode.REVIEW:
            return self.service.get_due_review_words
        if self.session_mode is StudySessionMode.PRACTICE:
            if self.practice_service is None:
                raise RuntimeError("PracticeService is unavailable")
            return partial(
                self.practice_service.get_words,
                self.practice_scope,
                exclude_word_ids=tuple(self._practice_completed_ids),
            )
        return self.service.get_due_words

    def _queue_loaded(self, items: list[ReviewItem]) -> None:
        self.queue = list(items)
        self._session_loaded += len(self.queue)
        if self.queue and self.on_session_state_changed:
            self.on_session_state_changed(True)
        self._show_next()

    def _show_next(self) -> None:
        if not self.queue:
            self.current = None
            self._learning_intro_active = False
            self._sync_assistant_context()
            if self.on_session_state_changed:
                self.on_session_state_changed(False)
            complete_title, complete_detail = self._completion_copy()
            self.word_label.setText(complete_title)
            self.phonetic_label.setText(complete_detail)
            self.answer_label.clear()
            self.example_label.clear()
            self.example_translation_label.clear()
            self.favorite_button.hide()
            self.mastered_button.hide()
            self._hide_learning_aids()
            self.choice_frame.hide()
            self.reveal_button.setEnabled(False)
            if self.session_mode in {
                StudySessionMode.COMBINED,
                StudySessionMode.LEARN,
            }:
                self.continue_button.setText("继续学习 5 个新词")
                self.continue_button.setEnabled(True)
                self.continue_button.show()
            else:
                self.continue_button.hide()
            self._set_ratings_enabled(False)
            self.phase_label.setText("本轮完成")
            if self._session_completed:
                self.progress.setText(f"本轮已完成 {self._session_completed} 个")
            else:
                self.progress.setText(self._empty_progress_text())
            self._refresh_undo_button()
            return
        self.current = self.queue.pop(0)
        self._sync_assistant_context()
        self.word_label.setText(self.current.word)
        self.phonetic_label.setText(self.current.phonetic)
        self._refresh_favorite_button()
        self._refresh_mastered_button()
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self._reset_choice_state()
        self.continue_button.hide()
        self.choice_widget.set_options(self.current.meaning_options)
        self.reveal_button.setEnabled(True)
        self.reveal_button.show()
        self._set_ratings_enabled(False)
        if self.session_mode is StudySessionMode.LEARN:
            self._learning_intro_active = True
            self.phase_label.setText("阶段 1/3 · 阅读新词")
            self.answer_label.setText(self.current.meaning)
            self.example_label.setText(self.current.example)
            self.example_translation_label.setText(self.current.example_translation)
            self._render_learning_aids()
            self.choice_widget.hide()
            self.reveal_button.setText("看完了，开始小测  Space")
        else:
            self._learning_intro_active = False
            self.phase_label.setText("阶段 1/2 · 选择释义")
            self.reveal_button.setText("想不起来，显示释义  Space")
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
        if self._learning_intro_active:
            self._begin_learning_quiz()
            return
        self.used_hint = True
        self.selected_answer = ""
        self.choice_correct = None
        self.answer_label.setText(self.current.meaning)
        self.example_label.setText(self.current.example)
        self.example_translation_label.setText(self.current.example_translation)
        self._render_learning_aids()
        self.choice_widget.disable_and_highlight()
        self.choice_widget.hide()
        self.reveal_button.hide()
        self._set_ratings_enabled(True)
        self._rating_shortcuts_ready_at = (
            time.monotonic() + RATING_SHORTCUT_GUARD_SECONDS
        )
        self.phase_label.setText(self._rating_phase_text())

    def _begin_learning_quiz(self) -> None:
        if self.current is None:
            return
        self._learning_intro_active = False
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self._hide_learning_aids()
        self.choice_widget.set_options(self.current.meaning_options)
        self.reveal_button.setText("想不起来，显示释义  Space")
        self.reveal_button.show()
        self.phase_label.setText("阶段 2/3 · 检测是否记住")
        self.started_at = time.monotonic()

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
        self._render_learning_aids()
        self.reveal_button.hide()
        self._set_ratings_enabled(True)
        self._rating_shortcuts_ready_at = (
            time.monotonic() + RATING_SHORTCUT_GUARD_SECONDS
        )
        self.phase_label.setText(self._rating_phase_text())

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
        if self.session_mode is StudySessionMode.PRACTICE:
            if self.practice_service is None:
                self._pending_review_item = None
                raise RuntimeError("PracticeService is unavailable")
            self.phase_label.setText("正在保存练习结果…")
            self.worker_action = "practice_submit"
            is_correct = (
                self.choice_correct
                if self.choice_correct is not None
                else rating is not Rating.AGAIN
            )
            self.worker = AsyncWorker(
                partial(
                    self.practice_service.record_attempt,
                    self.current.word_id,
                    is_correct=is_correct,
                    response_time_ms=response_ms,
                    scope=self.practice_scope,
                    question_type=self._question_type(),
                    user_answer=self.selected_answer,
                ),
                parent=self,
            )
            self.worker.result_ready.connect(self._practice_saved)
        else:
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

    def toggle_mastered(self) -> None:
        if (
            self.worker is not None
            or self.current is None
            or self.mastery_service is None
        ):
            return
        self.mastered_button.setEnabled(False)
        self.favorite_button.setEnabled(False)
        self.worker_action = "mastered"
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

    def _favorite_updated(self, result: FavoriteUpdate) -> None:
        if self.current is None or self.current.word_id != result.word_id:
            logger.error("Favorite result does not match the current review card")
            return
        self.current = replace(self.current, is_favorite=result.is_favorite)
        self._refresh_favorite_button()

    def _mastered_updated(self, result: MasteryUpdate) -> None:
        if self.current is None or self.current.word_id != result.word_id:
            logger.error("Mastery result does not match the current review card")
            return
        self.current = None
        if self.on_reviewed:
            self.on_reviewed()
        if self.queue:
            self._show_next()
            return
        self._sync_assistant_context()
        self.word_label.setText("正在检查剩余学习任务…")
        self.phonetic_label.clear()
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self.favorite_button.hide()
        self.mastered_button.hide()
        self._hide_learning_aids()
        self.choice_frame.hide()
        self.reveal_button.setEnabled(False)
        self.progress.clear()
        self.phase_label.setText("正在检查剩余任务…")
        self._load_after_worker = True

    def report_learning_aid_issue(self) -> None:
        if (
            self.worker is not None
            or self.current is None
            or not self.current.has_learning_aid
            or self.learning_aid_feedback_service is None
        ):
            return
        labels = [label for label, _issue in LEARNING_AID_ISSUE_CHOICES]
        current_index = next(
            (
                index
                for index, (_label, issue) in enumerate(LEARNING_AID_ISSUE_CHOICES)
                if issue is self.current.learning_aid_feedback
            ),
            0,
        )
        selected_label, accepted = QInputDialog.getItem(
            self,
            "反馈学习辅助内容",
            "请选择最主要的问题：",
            labels,
            current_index,
            False,
        )
        if not accepted:
            return
        issue_by_label = dict(LEARNING_AID_ISSUE_CHOICES)
        issue_type = issue_by_label.get(selected_label)
        if issue_type is None:
            return
        self._set_ratings_enabled(False)
        self.learning_aid_report_button.setEnabled(False)
        self.learning_aid_status_label.setText("正在记录内容反馈…")
        self.phase_label.setText("正在记录内容反馈…")
        self.worker_action = "learning_aid_feedback"
        self.worker = AsyncWorker(
            self.learning_aid_feedback_service.report_issue,
            self.current.word_id,
            issue_type,
            parent=self,
        )
        self.worker.result_ready.connect(self._learning_aid_feedback_saved)
        self.worker.failed.connect(self._task_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _learning_aid_feedback_saved(
        self,
        result: LearningAidFeedbackUpdate,
    ) -> None:
        if self.current is None or self.current.word_id != result.word_id:
            logger.error("Learning-aid feedback does not match current review card")
            return
        self.current = replace(
            self.current,
            learning_aid_feedback=result.issue_type,
        )

    def unlock_extra_study(self) -> None:
        if (
            self.session_mode not in {StudySessionMode.COMBINED, StudySessionMode.LEARN}
            or self.worker is not None
            or self.current is not None
        ):
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
            self._sync_assistant_context()
            self.word_label.setText("正在检查剩余复习任务…")
            self.phonetic_label.clear()
            self.answer_label.clear()
            self.example_label.clear()
            self.example_translation_label.clear()
            self.favorite_button.hide()
            self.mastered_button.hide()
            self._hide_learning_aids()
            self.choice_frame.hide()
            self.reveal_button.setEnabled(False)
            self.progress.clear()
            self.phase_label.setText("正在检查剩余任务…")
            self._load_after_worker = True

    def _practice_saved(self, submission: PracticeSubmission) -> None:
        if self._pending_review_item is None:
            logger.error("Saved practice has no pending UI item")
            return
        if submission.word_id != self._pending_review_item.word_id:
            logger.error("Saved practice does not match the pending UI item")
            return
        self._practice_completed_ids.add(submission.word_id)
        self._pending_review_item = None
        self._session_completed += 1
        if self.on_reviewed:
            self.on_reviewed()
        if self.queue:
            self._show_next()
        else:
            self.current = None
            self._sync_assistant_context()
            self.word_label.setText("正在检查这个范围的剩余单词…")
            self.phonetic_label.clear()
            self.answer_label.clear()
            self.example_label.clear()
            self.example_translation_label.clear()
            self.favorite_button.hide()
            self.mastered_button.hide()
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
        if self.worker_action == "learning_aid_feedback":
            logger.error("Could not save learning-aid feedback: %s", message)
            self._show_error("暂时无法记录内容反馈，请稍后重试。")
            return
        if self.worker_action == "favorite":
            logger.error("Could not update favorite: %s", message)
            self._refresh_favorite_button()
            self._show_error("暂时无法更新收藏，请稍后重试。")
            return
        if self.worker_action == "mastered":
            logger.error("Could not update mastered state: %s", message)
            self._refresh_favorite_button()
            self._refresh_mastered_button()
            self._show_error("暂时无法更新完全掌握状态，请稍后重试。")
            return
        if self.worker_action in {"submit", "practice_submit"}:
            logger.error("Study submission failed: %s", message)
            self._pending_review_item = None
            self._set_ratings_enabled(self.current is not None)
            self.phase_label.setText(self._rating_phase_text())
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
                    self._rating_phase_text()
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
        self._sync_assistant_context()
        if self.on_session_state_changed:
            self.on_session_state_changed(False)
        self.word_label.setText("暂时无法加载复习任务")
        self.phonetic_label.clear()
        self.answer_label.clear()
        self.example_label.clear()
        self.example_translation_label.clear()
        self.favorite_button.hide()
        self.mastered_button.hide()
        self._hide_learning_aids()
        self.reveal_button.setEnabled(False)
        self.continue_button.hide()
        self._set_ratings_enabled(False)
        self.progress.clear()
        self.phase_label.setText("加载失败")
        self._refresh_undo_button()
        self._show_error("暂时无法读取复习任务，请稍后重试。")

    def _worker_finished(self) -> None:
        finished_action = self.worker_action
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.worker_action = None
        if self._load_after_worker:
            self._load_after_worker = False
            reset_progress = self._reset_progress_after_worker
            self._reset_progress_after_worker = False
            self._start_queue_load(reset_progress=reset_progress)
            return
        if finished_action == "learning_aid_feedback" and self.current is not None:
            self._set_ratings_enabled(True)
            self.phase_label.setText(self._rating_phase_text())
            self._render_learning_aids()
        self._refresh_favorite_button()
        self._refresh_mastered_button()
        self._refresh_undo_button()

    def _render_learning_aids(self) -> None:
        if self.current is None:
            return
        self._show_learning_aids(
            self.current.collocations,
            self.current.word_family,
            has_learning_aid=self.current.has_learning_aid,
            feedback_reported=self.current.learning_aid_feedback is not None,
            feedback_enabled=(
                self.learning_aid_feedback_service is not None and self.worker is None
            ),
        )

    def _set_ratings_enabled(self, enabled: bool) -> None:
        for rating, button in self.rating_buttons.items():
            if self.session_mode is StudySessionMode.PRACTICE:
                allowed = rating in {Rating.AGAIN, Rating.GOOD}
                if self.choice_correct is False:
                    allowed = rating is Rating.AGAIN
                elif self.choice_correct is True:
                    allowed = rating is Rating.GOOD
                button.setEnabled(enabled and allowed)
            else:
                button.setEnabled(
                    enabled
                    and (self.choice_correct is not False or rating is Rating.AGAIN)
                )

    def _handle_number_key(self, index: int) -> None:
        if self._assistant_has_focus():
            return
        if self.choice_widget.choose_with_number(index):
            return
        if time.monotonic() < self._rating_shortcuts_ready_at:
            return
        if self.session_mode is StudySessionMode.PRACTICE:
            if index == 0:
                self.submit(Rating.AGAIN)
            elif index == 1:
                self.submit(Rating.GOOD)
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

    def _refresh_mastered_button(self) -> None:
        if self.mastery_service is None or self.current is None:
            self.mastered_button.hide()
            return
        self.mastered_button.setText("✓ 完全掌握")
        self.mastered_button.setEnabled(self.worker is None)
        self.mastered_button.show()

    def _clear_undo(self) -> None:
        self._last_reviewed_item = None
        self._last_submission = None
        self.undo_button.hide()

    def _refresh_undo_button(self) -> None:
        available = (
            self.session_mode is not StudySessionMode.PRACTICE
            and self._last_reviewed_item is not None
            and self._last_submission is not None
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

    def _practice_scope_changed(self, _index: int) -> None:
        if self.practice_scope_combo is None:
            return
        value = self.practice_scope_combo.currentData()
        if not isinstance(value, str):
            return
        selected = PracticeScope(value)
        if selected is self.practice_scope:
            return
        self.practice_scope = selected
        if self.worker is not None:
            self._load_after_worker = True
            self._reset_progress_after_worker = True
            return
        self.load_queue()

    def _page_title(self) -> str:
        return {
            StudySessionMode.COMBINED: "单词复习",
            StudySessionMode.LEARN: "学习新词",
            StudySessionMode.REVIEW: "到期复习",
            StudySessionMode.PRACTICE: "自由复习",
        }[self.session_mode]

    def _loading_text(self) -> str:
        return {
            StudySessionMode.COMBINED: "正在加载复习任务…",
            StudySessionMode.LEARN: "正在加载待学新词…",
            StudySessionMode.REVIEW: "正在加载到期复习…",
            StudySessionMode.PRACTICE: "正在加载自由复习…",
        }[self.session_mode]

    def _completion_copy(self) -> tuple[str, str]:
        return {
            StudySessionMode.COMBINED: (
                "今日复习已完成",
                "做得很好，稍后再回来看看吧。",
            ),
            StudySessionMode.LEARN: (
                "当前待学新词已完成",
                "可以继续解锁 5 个新词，或转到到期复习。",
            ),
            StudySessionMode.REVIEW: (
                "当前没有到期复习",
                "已学单词会在 FSRS 安排的时间重新出现。",
            ),
            StudySessionMode.PRACTICE: (
                "这个范围已经练完一轮",
                "自由复习只记录练习结果，不会推迟正式复习日期。",
            ),
        }[self.session_mode]

    def _empty_progress_text(self) -> str:
        return {
            StudySessionMode.COMBINED: "0 个待复习",
            StudySessionMode.LEARN: "0 个待学新词",
            StudySessionMode.REVIEW: "0 个到期复习",
            StudySessionMode.PRACTICE: "0 个可练单词",
        }[self.session_mode]

    def _rating_phase_text(self) -> str:
        return {
            StudySessionMode.COMBINED: "阶段 2/2 · 评价回忆难度",
            StudySessionMode.LEARN: "阶段 3/3 · 评价初次学习难度",
            StudySessionMode.REVIEW: "阶段 2/2 · 评价回忆难度",
            StudySessionMode.PRACTICE: "阶段 2/2 · 记录练习结果",
        }[self.session_mode]

    def toggle_assistant(self) -> None:
        if self.assistant_panel is None or self.assistant_toggle is None:
            return
        show_panel = self.assistant_panel.isHidden()
        self.assistant_panel.setVisible(show_panel)
        self.assistant_toggle.setText("隐藏 AI 助手" if show_panel else "显示 AI 助手")
        if show_panel and self.workspace_splitter is not None:
            self.workspace_splitter.setSizes(list(STUDY_WORKSPACE_INITIAL_SIZES))

    def _assistant_context(self) -> ChatContext | None:
        if self.current is None:
            return None
        collocations = "; ".join(self.current.collocations)
        word_family = "; ".join(self.current.word_family)
        return ChatContext(
            label=self.current.word,
            content=(
                f"word={self.current.word}\n"
                f"phonetic={self.current.phonetic}\n"
                f"meaning={self.current.meaning}\n"
                f"example={self.current.example}\n"
                f"collocations={collocations}\n"
                f"word_family={word_family}"
            ),
        )

    def _sync_assistant_context(self) -> None:
        if self.assistant_panel is not None:
            self.assistant_panel.context_changed()

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
