from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from sqlalchemy import func, select

from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.domain.fsrs_scheduler import Rating
from app.services.review_service import ReviewService
from app.ui.review_page import ReviewPage
from app.utils.datetime_utils import UTC


def test_review_page_completes_one_review(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    assert page.current is not None
    assert page.current.word_id == word_id
    page.reveal_answer()
    page.submit(Rating.GOOD)
    app.processEvents()

    assert page.current is None
    with database.session() as session:
        assert session.scalar(select(func.count(ReviewLog.id))) == 1
    page.deleteLater()


def test_review_page_loads_another_batch_after_thirty(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    with database.session() as session:
        for index in range(30):
            word = Word(
                word=f"batchword{index}",
                meaning=f"批次词 {index}",
                level=WordLevel.CET4,
            )
            word.learning_state = LearningState(
                next_review_at=datetime(2026, 1, 1, tzinfo=UTC)
            )
            session.add(word)

    page = ReviewPage(ReviewService(database))
    page.load_queue()
    for index in range(31):
        assert page.current is not None
        page.reveal_answer()
        page.submit(Rating.GOOD)
        app.processEvents()
        if index == 29:
            assert page.current is not None

    assert page.current is None
    with database.session() as session:
        assert session.scalar(select(func.count(ReviewLog.id))) == 31
    page.deleteLater()


def test_failed_queue_reload_disables_stale_review_card(
    database,
    word_id,
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    service = ReviewService(database)
    page = ReviewPage(service)
    monkeypatch.setattr(page, "_show_error", lambda _message: None)
    page.load_queue()
    page.reveal_answer()

    def fail_to_load():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "get_due_words", fail_to_load)
    page.load_queue()
    app.processEvents()

    assert page.current is None
    assert page.queue == []
    assert page.reveal_button.isEnabled() is False
    assert all(not button.isEnabled() for button in page.rating_buttons.values())
    page.deleteLater()
