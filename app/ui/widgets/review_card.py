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
        self.answer_label = self._centered_label("")
        self.answer_label.setWordWrap(True)
        self.answer_label.setStyleSheet("font-size: 18px; color: #334155;")
        self.example_label = self._centered_label("")
        self.example_label.setWordWrap(True)
        self.example_label.setStyleSheet("color: #64748b; font-style: italic;")
        self.choice_widget = MeaningQuizWidget()
        self.choice_widget.option_selected.connect(on_choice)
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
        layout.addSpacing(16)
        layout.addWidget(self.answer_label)
        layout.addWidget(self.example_label)
        layout.addWidget(self.choice_widget)
        layout.addSpacing(12)
        layout.addWidget(self.reveal_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.continue_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(rating_row)
        layout.addWidget(self.undo_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    @staticmethod
    def _centered_label(text: str, object_name: str = "") -> QLabel:
        label = QLabel(text)
        if object_name:
            label.setObjectName(object_name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label
