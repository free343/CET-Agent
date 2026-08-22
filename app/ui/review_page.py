"""Keyboard-friendly vocabulary review screen."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.fsrs_scheduler import Rating
from app.services.review_service import ReviewItem, ReviewService

logger = logging.getLogger(__name__)


class ReviewPage(QWidget):
    def __init__(
        self,
        service: ReviewService,
        on_reviewed: Callable[[], None] | None = None,
        on_session_state_changed: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.on_reviewed = on_reviewed
        self.on_session_state_changed = on_session_state_changed
        self.queue: list[ReviewItem] = []
        self.current: ReviewItem | None = None
        self.started_at = time.monotonic()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(18)
        heading = QHBoxLayout()
        title = QLabel("单词复习")
        title.setObjectName("PageTitle")
        self.progress = QLabel("")
        self.progress.setStyleSheet("color: #64748b;")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.progress)
        outer.addLayout(heading)

        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumHeight(420)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(44, 36, 44, 36)
        card_layout.setSpacing(14)
        self.word_label = QLabel("准备开始")
        self.word_label.setObjectName("Word")
        self.word_label.setAlignment(QtAlignmentCenter)
        self.phonetic_label = QLabel("")
        self.phonetic_label.setObjectName("Phonetic")
        self.phonetic_label.setAlignment(QtAlignmentCenter)
        self.answer_label = QLabel("")
        self.answer_label.setWordWrap(True)
        self.answer_label.setAlignment(QtAlignmentCenter)
        self.answer_label.setStyleSheet("font-size: 18px; color: #334155;")
        self.example_label = QLabel("")
        self.example_label.setWordWrap(True)
        self.example_label.setAlignment(QtAlignmentCenter)
        self.example_label.setStyleSheet("color: #64748b; font-style: italic;")

        self.reveal_button = QPushButton("显示释义  Space")
        self.reveal_button.setObjectName("PrimaryButton")
        self.reveal_button.clicked.connect(self.reveal_answer)
        self.rating_row = QHBoxLayout()
        self.rating_buttons: dict[Rating, QPushButton] = {}
        for rating, label in (
            (Rating.AGAIN, "1  Again"),
            (Rating.HARD, "2  Hard"),
            (Rating.GOOD, "3  Good"),
            (Rating.EASY, "4  Easy"),
        ):
            button = QPushButton(label)
            button.setObjectName("RatingButton")
            button.clicked.connect(
                lambda _checked=False, value=rating: self.submit(value)
            )
            self.rating_buttons[rating] = button
            self.rating_row.addWidget(button)

        card_layout.addStretch()
        card_layout.addWidget(self.word_label)
        card_layout.addWidget(self.phonetic_label)
        card_layout.addSpacing(16)
        card_layout.addWidget(self.answer_label)
        card_layout.addWidget(self.example_label)
        card_layout.addSpacing(12)
        card_layout.addWidget(self.reveal_button, alignment=QtAlignmentCenter)
        card_layout.addLayout(self.rating_row)
        card_layout.addStretch()
        outer.addWidget(card)
        outer.addStretch()

        QShortcut(QKeySequence("Space"), self, self.reveal_answer)
        for key, rating in zip(("1", "2", "3", "4"), Rating, strict=True):
            QShortcut(QKeySequence(key), self, partial(self.submit, rating))
        self._set_ratings_enabled(False)

    def load_queue(self) -> None:
        try:
            self.queue = self.service.get_due_words()
            if self.on_session_state_changed:
                self.on_session_state_changed(bool(self.queue))
            self._show_next()
        except Exception:  # GUI boundary: log detail, show safe message.
            logger.exception("Could not load review queue")
            self.queue = []
            self.current = None
            if self.on_session_state_changed:
                self.on_session_state_changed(False)
            self.word_label.setText("暂时无法加载复习任务")
            self.phonetic_label.clear()
            self.answer_label.clear()
            self.example_label.clear()
            self.reveal_button.setEnabled(False)
            self._set_ratings_enabled(False)
            self.progress.clear()
            self._show_error("暂时无法读取复习任务，请稍后重试。")

    def _show_next(self) -> None:
        if not self.queue:
            self.current = None
            if self.on_session_state_changed:
                self.on_session_state_changed(False)
            self.word_label.setText("今日复习已完成")
            self.phonetic_label.setText("做得很好，稍后再回来看看吧。")
            self.answer_label.clear()
            self.example_label.clear()
            self.reveal_button.setEnabled(False)
            self._set_ratings_enabled(False)
            self.progress.setText("0 个待复习")
            return
        self.current = self.queue.pop(0)
        self.word_label.setText(self.current.word)
        self.phonetic_label.setText(self.current.phonetic)
        self.answer_label.clear()
        self.example_label.clear()
        self.reveal_button.setEnabled(True)
        self.reveal_button.show()
        self._set_ratings_enabled(False)
        self.progress.setText(f"还剩 {len(self.queue) + 1} 个")
        self.started_at = time.monotonic()

    def reveal_answer(self) -> None:
        if self.current is None:
            return
        self.answer_label.setText(self.current.meaning)
        self.example_label.setText(self.current.example)
        self.reveal_button.hide()
        self._set_ratings_enabled(True)

    def submit(self, rating: Rating) -> None:
        if self.current is None or not self.rating_buttons[rating].isEnabled():
            return
        response_ms = int((time.monotonic() - self.started_at) * 1000)
        try:
            self.service.submit_review(self.current.word_id, rating, response_ms)
        except Exception:  # GUI must survive database and validation errors.
            logger.exception("Review submission failed")
            self._show_error("本次记录未保存，请稍后重试。")
            return
        if self.on_reviewed:
            self.on_reviewed()
        if self.queue:
            self._show_next()
        else:
            # get_due_words is intentionally capped. After one batch finishes,
            # query again instead of incorrectly claiming that all work is done.
            self.current = None
            self.load_queue()

    def _set_ratings_enabled(self, enabled: bool) -> None:
        for button in self.rating_buttons.values():
            button.setEnabled(enabled)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "CET-Agent", message)


# Kept as a local alias to avoid repeating a long Qt enum in the layout code.
from PySide6.QtCore import Qt

QtAlignmentCenter = Qt.AlignmentFlag.AlignCenter
