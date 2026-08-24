"""Presentation-only review card shared by the review workflow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.domain.fsrs_scheduler import Rating
from app.services.lexical_fact_view import LexicalFactSection
from app.ui.widgets.english_quiz_widget import EnglishQuizWidget
from app.ui.widgets.meaning_quiz_widget import MeaningQuizWidget


class ReviewCardWidget(QFrame):
    LEARNING_AID_STACK_WIDTH = 680

    def __init__(
        self,
        *,
        on_reveal: Callable[[], None],
        on_unlock: Callable[[], None],
        on_undo: Callable[[], None],
        on_favorite: Callable[[], None],
        on_mastered: Callable[[], None] | None = None,
        on_choice: Callable[[int], None],
        on_rating: Callable[[Rating], None],
        on_report_learning_aid: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.setMinimumHeight(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 36, 44, 36)
        layout.setSpacing(14)
        self.phase_label = self._centered_label("")
        self.phase_label.setStyleSheet("color: #64748b; font-weight: 600;")
        self.word_label = self._centered_label("准备开始", "Word")
        self.phonetic_label = self._centered_label("", "Phonetic")
        self.favorite_button = QPushButton("☆ 收藏")
        self.favorite_button.setObjectName("FavoriteButton")
        self.favorite_button.clicked.connect(on_favorite)
        self.mastered_button = QPushButton("✓ 完全掌握")
        self.mastered_button.setObjectName("MasteredButton")
        if on_mastered is not None:
            self.mastered_button.clicked.connect(on_mastered)
        else:
            self.mastered_button.hide()
        self.answer_label = self._centered_label("")
        self.answer_label.setWordWrap(True)
        self.answer_label.setStyleSheet("font-size: 18px; color: #334155;")
        self.example_label = self._centered_label("")
        self.example_label.setWordWrap(True)
        self.example_label.setStyleSheet("color: #64748b; font-style: italic;")
        self.example_translation_label = self._centered_label("")
        self.example_translation_label.setWordWrap(True)
        self.example_translation_label.setStyleSheet("color: #94a3b8;")
        self.choice_widget = MeaningQuizWidget()
        self.choice_widget.option_selected.connect(on_choice)
        self.english_choice_widget = EnglishQuizWidget()
        self.learning_aids_frame = QFrame()
        self.learning_aids_frame.setObjectName("LearningAids")
        aids_outer_layout = QVBoxLayout(self.learning_aids_frame)
        aids_outer_layout.setContentsMargins(18, 12, 18, 12)
        aids_outer_layout.setSpacing(10)
        self.learning_aids_scroll = QScrollArea()
        self.learning_aids_scroll.setObjectName("LearningAidsScroll")
        self.learning_aids_scroll.setWidgetResizable(True)
        self.learning_aids_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.learning_aids_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.learning_aids_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.learning_aids_scroll.setMinimumHeight(112)
        self.learning_aids_scroll.setMaximumHeight(210)
        self.learning_aids_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.learning_aids_content = QWidget()
        self.learning_aids_content.setObjectName("LearningAidsContent")
        self.learning_aids_content_layout = QBoxLayout(
            QBoxLayout.Direction.LeftToRight,
            self.learning_aids_content,
        )
        self.learning_aids_content_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetMinAndMaxSize
        )
        self.learning_aids_content_layout.setContentsMargins(0, 0, 8, 0)
        self.learning_aids_content_layout.setSpacing(24)
        self._learning_aid_groups: dict[str, QWidget] = {}
        self._learning_aid_titles: dict[str, QLabel] = {}

        def make_group(key: str, title: str, label: QLabel) -> QWidget:
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            title_label = QLabel(title)
            title_label.setObjectName("LearningAidTitle")
            label.setWordWrap(True)
            group_layout.addWidget(title_label)
            group_layout.addWidget(label)
            self._learning_aid_groups[key] = group
            self._learning_aid_titles[key] = title_label
            return group

        self.collocations_label = QLabel("")
        self.word_family_label = QLabel("")
        self.forms_label = QLabel("")
        self.relations_label = QLabel("")
        for key, title, section_label in (
            ("forms", "词形", self.forms_label),
            ("collocations", "固定搭配", self.collocations_label),
            ("relations", "近反义", self.relations_label),
            ("derivatives", "派生词", self.word_family_label),
        ):
            self.learning_aids_content_layout.addWidget(
                make_group(key, title, section_label), 1
            )
        self.learning_aids_scroll.setWidget(self.learning_aids_content)
        aids_outer_layout.addWidget(self.learning_aids_scroll)
        feedback_row = QHBoxLayout()
        self.learning_aid_status_label = QLabel("")
        self.learning_aid_status_label.setObjectName("LearningAidStatus")
        self.learning_aid_status_label.setWordWrap(False)
        feedback_row.addWidget(self.learning_aid_status_label, 1)
        self.learning_aid_report_button = QPushButton("内容有问题")
        self.learning_aid_report_button.setObjectName("LearningAidReportButton")
        if on_report_learning_aid is not None:
            self.learning_aid_report_button.clicked.connect(on_report_learning_aid)
        else:
            self.learning_aid_report_button.hide()
        feedback_row.addWidget(self.learning_aid_report_button)
        self.learning_aid_feedback_row = QWidget()
        self.learning_aid_feedback_row.setLayout(feedback_row)
        aids_outer_layout.addWidget(self.learning_aid_feedback_row)
        self.learning_aids_frame.hide()
        self.spelling_panel = QFrame()
        spelling_layout = QHBoxLayout(self.spelling_panel)
        spelling_layout.setContentsMargins(0, 4, 0, 4)
        spelling_layout.setSpacing(8)
        self.spelling_input = QLineEdit()
        self.spelling_input.setPlaceholderText("输入英语拼写")
        self.spelling_input.setClearButtonEnabled(True)
        self.spelling_submit_button = QPushButton("提交拼写")
        self.self_confirm_button = QPushButton("我已会拼写，直接完成")
        spelling_layout.addWidget(self.spelling_input, 1)
        spelling_layout.addWidget(self.spelling_submit_button)
        spelling_layout.addWidget(self.self_confirm_button)
        self.spelling_panel.hide()
        self.reveal_button = QPushButton("显示释义  Space")
        self.reveal_button.setObjectName("PrimaryButton")
        self.reveal_button.clicked.connect(on_reveal)
        self.continue_button = QPushButton("继续学习 5 个新词")
        self.continue_button.setObjectName("PrimaryButton")
        self.continue_button.clicked.connect(on_unlock)
        self.continue_button.hide()
        self.undo_button = QPushButton("撤销上一条评分  Ctrl+Z")
        self.undo_button.setToolTip("恢复该单词评分前的复习计划与统计")
        self.undo_button.clicked.connect(on_undo)
        self.undo_button.hide()
        self.rating_buttons: dict[Rating, QPushButton] = {}
        rating_row = QHBoxLayout()
        for rating, label in (
            (Rating.AGAIN, "1  Again"),
            (Rating.HARD, "2  Hard"),
            (Rating.GOOD, "3  Good"),
            (Rating.EASY, "4  Easy"),
        ):
            button = QPushButton(label)
            button.setObjectName("RatingButton")
            button.clicked.connect(
                lambda _checked=False, value=rating: on_rating(value)
            )
            self.rating_buttons[rating] = button
            rating_row.addWidget(button)

        layout.addStretch()
        layout.addWidget(self.phase_label)
        layout.addWidget(self.word_label)
        layout.addWidget(self.phonetic_label)
        status_row = QHBoxLayout()
        status_row.addStretch()
        status_row.addWidget(self.favorite_button)
        status_row.addWidget(self.mastered_button)
        status_row.addStretch()
        layout.addLayout(status_row)
        layout.addSpacing(16)
        layout.addWidget(self.answer_label)
        layout.addWidget(self.example_label)
        layout.addWidget(self.example_translation_label)
        layout.addWidget(self.choice_widget)
        layout.addWidget(self.english_choice_widget)
        layout.addWidget(self.spelling_panel)
        layout.addWidget(self.learning_aids_frame)
        layout.addSpacing(12)
        layout.addWidget(self.reveal_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.continue_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(rating_row)
        layout.addWidget(self.undo_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    def show_learning_aids(
        self,
        collocations: tuple[str, ...],
        word_family: tuple[str, ...],
        *,
        has_learning_aid: bool,
        feedback_reported: bool = False,
        feedback_enabled: bool = False,
        lexical_sections: tuple[LexicalFactSection, ...] | None = None,
    ) -> None:
        if lexical_sections is not None:
            self._show_dynamic_sections(
                lexical_sections,
                has_learning_aid=has_learning_aid,
                feedback_reported=feedback_reported,
                feedback_enabled=feedback_enabled,
            )
            return
        for key in self._learning_aid_groups:
            self._learning_aid_groups[key].setVisible(
                key in {"collocations", "derivatives"}
            )
        if has_learning_aid:
            collocation_empty = "暂无可靠的固定搭配"
            family_empty = "暂无可靠的同族 / 派生词"
        else:
            collocation_empty = family_empty = "内容尚未生成"
        self.collocations_label.setText(
            self._format_learning_aids(collocations, empty_text=collocation_empty)
        )
        self.word_family_label.setText(
            self._format_learning_aids(word_family, empty_text=family_empty)
        )
        if has_learning_aid:
            status = "AI · 已反馈" if feedback_reported else "AI · 未审核"
            status_tooltip = (
                "AI 生成内容，尚未人工审核；已记录你的问题反馈。"
                if feedback_reported
                else "AI 生成内容，尚未人工审核。"
            )
        else:
            status = "内容待生成"
            status_tooltip = "尚无已验证的学习辅助内容。"
        self.learning_aid_status_label.setText(status)
        self.learning_aid_status_label.setToolTip(status_tooltip)
        self.learning_aid_report_button.setText(
            "修改反馈" if feedback_reported else "内容有问题"
        )
        self.learning_aid_report_button.setVisible(
            has_learning_aid and feedback_enabled
        )
        self.learning_aid_report_button.setEnabled(feedback_enabled)
        self.learning_aids_content_layout.invalidate()
        self.learning_aids_content.adjustSize()
        self.learning_aids_frame.show()

    def _show_dynamic_sections(
        self,
        sections: tuple[LexicalFactSection, ...],
        *,
        has_learning_aid: bool,
        feedback_reported: bool,
        feedback_enabled: bool,
    ) -> None:
        section_by_key = {section.key: section for section in sections}
        for key, group in self._learning_aid_groups.items():
            section = section_by_key.get(key)
            visible = section is not None and bool(section.items)
            group.setVisible(visible)
            if not visible and key == "collocations":
                self.collocations_label.setText(
                    "暂无可靠的固定搭配" if has_learning_aid else "内容尚未生成"
                )
            if not visible and key == "derivatives":
                self.word_family_label.setText(
                    "暂无可靠的同族 / 派生词" if has_learning_aid else "内容尚未生成"
                )
            if not visible:
                continue
            assert section is not None
            label = {
                "forms": self.forms_label,
                "collocations": self.collocations_label,
                "relations": self.relations_label,
                "derivatives": self.word_family_label,
            }[key]
            label.setText(self._format_learning_aids(section.items))
            section_status = (
                "AI · 已反馈"
                if feedback_reported and not section.verified and section.reportable
                else section.status
            )
            self._learning_aid_titles[key].setText(
                f"{section.title} · {section_status}"
            )
        has_unreviewed = any(
            not section.verified and section.reportable for section in sections
        )
        if has_unreviewed:
            reported = feedback_reported or any(
                "已反馈" in section.status for section in sections if section.reportable
            )
            self.learning_aid_status_label.setText(
                "AI · 已反馈" if reported else "AI · 未审核"
            )
            self.learning_aid_status_label.setToolTip(
                "AI 生成内容，尚未人工审核；已记录你的问题反馈。"
                if reported
                else "AI 生成内容，尚未人工审核。"
            )
        else:
            self.learning_aid_status_label.setText("")
            self.learning_aid_status_label.setToolTip("")
        self.learning_aid_report_button.setVisible(has_unreviewed and feedback_enabled)
        self.learning_aid_report_button.setEnabled(feedback_enabled)
        self.learning_aid_feedback_row.setVisible(has_unreviewed and feedback_enabled)
        if not sections:
            # Keep the legacy labels populated for callers that inspect the
            # widget programmatically, while the learner-facing frame stays
            # hidden so no empty heading is rendered.
            self.collocations_label.setText("内容尚未生成")
            self.word_family_label.setText("内容尚未生成")
            self.learning_aids_frame.hide()
            return
        self.learning_aids_content_layout.invalidate()
        self.learning_aids_content.adjustSize()
        self.learning_aids_frame.show()

    def hide_learning_aids(self) -> None:
        self.learning_aids_frame.hide()

    @staticmethod
    def _format_learning_aids(
        items: tuple[str, ...],
        *,
        empty_text: str = "内容尚未生成",
    ) -> str:
        cleaned = [item.strip()[:120] for item in items[:6] if item.strip()]
        if not cleaned:
            return empty_text
        return "\n".join(cleaned)

    def resizeEvent(self, event: QResizeEvent) -> None:
        direction = (
            QBoxLayout.Direction.TopToBottom
            if event.size().width() < self.LEARNING_AID_STACK_WIDTH
            else QBoxLayout.Direction.LeftToRight
        )
        self.learning_aids_content_layout.setDirection(direction)
        self.learning_aids_content_layout.setSpacing(
            12 if direction is QBoxLayout.Direction.TopToBottom else 24
        )
        super().resizeEvent(event)

    @staticmethod
    def _centered_label(text: str, object_name: str = "") -> QLabel:
        label = QLabel(text)
        if object_name:
            label.setObjectName(object_name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label
