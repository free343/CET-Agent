"""Presentation-only review card shared by the review workflow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.domain.fsrs_scheduler import Rating
from app.ui.widgets.meaning_quiz_widget import MeaningQuizWidget


class ReviewCardWidget(QFrame):
    def __init__(
        self,
        *,
        on_reveal: Callable[[], None],
        on_unlock: Callable[[], None],
        on_undo: Callable[[], None],
        on_favorite: Callable[[], None],
        on_choice: Callable[[int], None],
        on_rating: Callable[[Rating], None],
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
        self.answer_label = self._centered_label("")
        self.answer_label.setWordWrap(True)
        self.answer_label.setStyleSheet("font-size: 18px; color: #334155;")
        self.example_label = self._centered_label("")
        self.example_label.setWordWrap(True)
        self.example_label.setStyleSheet("color: #64748b; font-style: italic;")
        self.choice_widget = MeaningQuizWidget()
        self.choice_widget.option_selected.connect(on_choice)
        self.learning_aids_frame = QFrame()
        self.learning_aids_frame.setObjectName("LearningAids")
        aids_layout = QHBoxLayout(self.learning_aids_frame)
        aids_layout.setContentsMargins(18, 12, 18, 12)
        aids_layout.setSpacing(24)
        collocations_group = QVBoxLayout()
        collocations_title = QLabel("固定搭配")
        collocations_title.setObjectName("LearningAidTitle")
        self.collocations_label = QLabel("")
        self.collocations_label.setWordWrap(True)
        collocations_group.addWidget(collocations_title)
        collocations_group.addWidget(self.collocations_label)
        family_group = QVBoxLayout()
        family_title = QLabel("同族 / 派生词")
        family_title.setObjectName("LearningAidTitle")
        self.word_family_label = QLabel("")
        self.word_family_label.setWordWrap(True)
        family_group.addWidget(family_title)
        family_group.addWidget(self.word_family_label)
        aids_layout.addLayout(collocations_group, 1)
        aids_layout.addLayout(family_group, 1)
        self.learning_aids_frame.hide()
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
        layout.addWidget(
            self.favorite_button,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        layout.addSpacing(16)
        layout.addWidget(self.answer_label)
        layout.addWidget(self.example_label)
        layout.addWidget(self.choice_widget)
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
    ) -> None:
        self.collocations_label.setText(self._format_learning_aids(collocations))
        self.word_family_label.setText(self._format_learning_aids(word_family))
        self.learning_aids_frame.show()

    def hide_learning_aids(self) -> None:
        self.learning_aids_frame.hide()

    @staticmethod
    def _format_learning_aids(items: tuple[str, ...]) -> str:
        cleaned = [item.strip()[:120] for item in items[:6] if item.strip()]
        if not cleaned:
            return "待 AI 逐词生成并校验"
        return "  ·  ".join(cleaned)

    @staticmethod
    def _centered_label(text: str, object_name: str = "") -> QLabel:
        label = QLabel(text)
        if object_name:
            label.setObjectName(object_name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label
