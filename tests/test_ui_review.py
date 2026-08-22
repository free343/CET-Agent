from __future__ import annotations

import os
import threading
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from sqlalchemy import func, select

from app.ai.schemas import AIAnswer
from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.domain.fsrs_scheduler import Rating
from app.domain.query_routing import QueryAssessment, QueryRoute
from app.services.review_service import ReviewService
from app.services.wordbook_service import WordbookService
from app.ui.review_page import ReviewPage
from app.utils.datetime_utils import UTC


def _wait_until_idle(page: ReviewPage, app: QApplication) -> None:
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()


def _add_choice_words(database) -> None:
    with database.session() as session:
        for index, meaning in enumerate(("采用", "状态", "补充"), start=1):
            word = Word(
                word=f"choiceword{index}",
                meaning=meaning,
                level=WordLevel.CET4,
                frequency=100 - index,
            )
            word.learning_state = LearningState(
                next_review_at=datetime(2027, 1, 1, tzinfo=UTC)
            )
            session.add(word)


class RecordingAssistantService:
    advanced_available = False

    def __init__(self) -> None:
        self.contexts: list[str | None] = []

    @staticmethod
    def route_question(_question: str) -> QueryAssessment:
        return QueryAssessment(QueryRoute.LOCAL, 0.9, "本地回答。")

    def ask(
        self,
        question: str,
        *,
        use_advanced: bool = False,
        history=(),
        context: str | None = None,
    ) -> AIAnswer:
        self.contexts.append(context)
        return AIAnswer(text=f"answer to {question}", confidence=0.9, model="fake")


def test_review_page_completes_one_review(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.word_id == word_id
    page.reveal_answer()
    page.submit(Rating.GOOD)
    _wait_until_idle(page, app)

    assert page.current is None
    with database.session() as session:
        assert session.scalar(select(func.count(ReviewLog.id))) == 1
    page.deleteLater()


def test_review_page_shows_phase_and_session_progress(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)

    assert "阶段 1/2" in page.phase_label.text()
    assert "1/1" in page.progress.text()
    page.reveal_answer()
    assert "阶段 2/2" in page.phase_label.text()
    page.deleteLater()


def test_review_page_toggles_current_word_favorite(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    wordbook = WordbookService(database)
    page = ReviewPage(ReviewService(database), wordbook_service=wordbook)

    page.load_queue()
    _wait_until_idle(page, app)
    assert page.favorite_button.text() == "☆ 收藏"

    page.favorite_button.click()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.is_favorite is True
    assert page.favorite_button.text() == "★ 已收藏"
    assert [item.word_id for item in wordbook.list_favorites()] == [word_id]

    page.favorite_button.click()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.is_favorite is False
    assert wordbook.list_favorites() == []
    page.deleteLater()


def test_learning_aids_appear_only_after_answer_without_invented_content(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    assert page.learning_aids_frame.isHidden() is True

    page.reveal_answer()

    assert page.learning_aids_frame.isHidden() is False
    assert page.choice_widget.isHidden() is True
    assert "待 AI 逐词生成并校验" in page.collocations_label.text()
    assert "待 AI 逐词生成并校验" in page.word_family_label.text()
    page.deleteLater()


def test_number_shortcut_requires_a_pause_between_choice_and_rating(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    _add_choice_words(database)
    page = ReviewPage(ReviewService(database))
    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None
    correct_index = next(
        index
        for index, option in enumerate(page.current.meaning_options)
        if option.word_id == word_id
    )

    page._handle_number_key(correct_index)
    page._handle_number_key(2)
    app.processEvents()

    assert page.worker is None
    with database.session() as session:
        assert session.scalar(select(func.count(ReviewLog.id))) == 0

    page._rating_shortcuts_ready_at = 0.0
    page._handle_number_key(2)
    _wait_until_idle(page, app)
    with database.session() as session:
        assert session.scalar(select(func.count(ReviewLog.id))) == 1
    page.deleteLater()


def test_review_page_can_undo_last_rating_and_reopen_the_card(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(ReviewService(database))
    page.load_queue()
    _wait_until_idle(page, app)
    page.reveal_answer()
    page.submit(Rating.GOOD)
    _wait_until_idle(page, app)

    assert page.current is None
    assert page.undo_button.isVisibleTo(page) is True
    page.undo_last_review()
    _wait_until_idle(page, app)

    assert page.current is not None
    assert page.current.word_id == word_id
    assert page.choice_correct is None
    assert "阶段 1/2" in page.phase_label.text()
    with database.session() as session:
        state = session.scalar(
            select(LearningState).where(LearningState.word_id == word_id)
        )
        assert state is not None
        assert state.review_count == 0
        assert session.scalar(select(func.count(ReviewLog.id))) == 0
    page.deleteLater()


def test_review_page_records_objective_meaning_choice(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    _add_choice_words(database)
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None
    correct_index = next(
        index
        for index, option in enumerate(page.current.meaning_options)
        if option.word_id == word_id
    )
    selected_meaning = page.current.meaning_options[correct_index].meaning
    page.choice_buttons[correct_index].click()

    assert page.choice_correct is True
    assert "回答正确" in page.answer_label.text()
    page.submit(Rating.GOOD)
    _wait_until_idle(page, app)

    with database.session() as session:
        review = session.scalar(select(ReviewLog))
        assert review is not None
        assert review.question_type == "meaning_choice_correct"
        assert review.user_answer == selected_meaning
        assert review.is_correct is True
    page.deleteLater()


def test_wrong_meaning_choice_only_allows_again(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    _add_choice_words(database)
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None
    wrong_index = next(
        index
        for index, option in enumerate(page.current.meaning_options)
        if option.word_id != word_id
    )
    page.choice_buttons[wrong_index].click()

    assert page.choice_correct is False
    assert page.rating_buttons[Rating.AGAIN].isEnabled() is True
    assert all(
        not button.isEnabled()
        for rating, button in page.rating_buttons.items()
        if rating is not Rating.AGAIN
    )
    page.deleteLater()


def test_completed_review_can_unlock_an_extra_pack(database) -> None:
    app = QApplication.instance() or QApplication([])
    with database.session() as session:
        for index in range(6):
            word = Word(
                word=f"extraword{index}",
                meaning=f"加练词 {index}",
                level=WordLevel.CET4,
                frequency=100 - index,
            )
            word.learning_state = LearningState(
                next_review_at=datetime(2027, 1, index + 1, tzinfo=UTC)
            )
            session.add(word)
    page = ReviewPage(ReviewService(database, WordLevel.CET4))

    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is None
    assert page.continue_button.isEnabled() is True
    page.continue_button.click()
    _wait_until_idle(page, app)

    assert page.current is not None
    assert page.current.word.startswith("extraword")
    assert page.service.due_count() == 5
    page.deleteLater()


def test_review_assistant_uses_current_word_snapshot(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    assistant = RecordingAssistantService()
    page = ReviewPage(
        ReviewService(database),
        assistant_service=assistant,
    )

    page.load_queue()
    _wait_until_idle(page, app)
    assert page.assistant_panel is not None
    page.assistant_panel.input.setText("怎么记？")
    page.assistant_panel.send()
    while page.assistant_panel.worker is not None:
        worker = page.assistant_panel.worker
        assert worker.wait(2_000)
        app.processEvents()

    assert assistant.contexts
    assert assistant.contexts[0] is not None
    assert "word=adapt" in assistant.contexts[0]
    assert page.used_hint is True
    assert "关于 adapt" in page.assistant_panel.transcript.toPlainText()
    page.deleteLater()


def test_review_shortcuts_do_not_capture_assistant_input(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(
        ReviewService(database),
        assistant_service=RecordingAssistantService(),
    )
    page.show()
    page.load_queue()
    _wait_until_idle(page, app)
    assert page.assistant_panel is not None

    page.assistant_panel.input.setFocus()
    QTest.keyClicks(page.assistant_panel.input, "word 1234")
    app.processEvents()

    assert page.assistant_panel.input.text() == "word 1234"
    assert page.answer_label.text() == ""
    assert page.choice_correct is None
    page.close()
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
    _wait_until_idle(page, app)
    for index in range(31):
        assert page.current is not None
        page.reveal_answer()
        page.submit(Rating.GOOD)
        _wait_until_idle(page, app)
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
    _wait_until_idle(page, app)
    page.reveal_answer()

    def fail_to_load():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "get_due_words", fail_to_load)
    page.load_queue()
    _wait_until_idle(page, app)

    assert page.current is None
    assert page.queue == []
    assert page.reveal_button.isEnabled() is False
    assert all(not button.isEnabled() for button in page.rating_buttons.values())
    page.deleteLater()


def test_review_database_calls_run_off_ui_thread(
    database,
    word_id,
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    service = ReviewService(database)
    ui_thread_id = threading.get_ident()
    load_thread_ids: list[int] = []
    submit_thread_ids: list[int] = []
    original_load = service.get_due_words
    original_submit = service.submit_review

    def tracked_load():
        load_thread_ids.append(threading.get_ident())
        return original_load()

    def tracked_submit(*args, **kwargs):
        submit_thread_ids.append(threading.get_ident())
        return original_submit(*args, **kwargs)

    monkeypatch.setattr(service, "get_due_words", tracked_load)
    monkeypatch.setattr(service, "submit_review", tracked_submit)
    page = ReviewPage(service)

    page.load_queue()
    _wait_until_idle(page, app)
    page.reveal_answer()
    page.submit(Rating.GOOD)
    _wait_until_idle(page, app)

    assert load_thread_ids
    assert submit_thread_ids
    assert all(thread_id != ui_thread_id for thread_id in load_thread_ids)
    assert all(thread_id != ui_thread_id for thread_id in submit_thread_ids)
    page.deleteLater()
