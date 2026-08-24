from __future__ import annotations

import os
import time
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

from PySide6.QtWidgets import QApplication
from sqlalchemy import select

from app.ai.schemas import AIAnswer
from app.db.models import (
    LearningState,
    ReviewLog,
    Word,
    WordAcquisitionState,
    WordLevel,
)
from app.domain.query_routing import QueryAssessment, QueryRoute
from app.services.acquisition_service import AcquisitionService
from app.services.mastery_service import MasteryService
from app.services.wordbook_service import WordbookService
from app.ui.acquisition_page import AcquisitionPage
from app.ui.mastered_page import MasteredPage
from app.utils.datetime_utils import UTC

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


class AcquisitionAssistantService:
    advanced_available = False

    @staticmethod
    def route_question(_question: str) -> QueryAssessment:
        return QueryAssessment(QueryRoute.LOCAL, 0.9, "本地回答。")

    @staticmethod
    def ask(
        question: str,
        *,
        use_advanced: bool = False,
        history=(),
        context: str | None = None,
    ) -> AIAnswer:
        return AIAnswer(text=f"answer to {question}", confidence=0.9, model="fake")


def _wait_until_idle(widget, app: QApplication) -> None:
    deadline = time.monotonic() + 4
    while widget.worker is not None and time.monotonic() < deadline:
        worker = widget.worker
        if worker is not None:
            assert worker.wait(2_000)
        app.processEvents()
    assert widget.worker is None


def _add_distractors(database) -> None:
    with database.session() as session:
        for index, word in enumerate(("adopt", "adept", "accept"), start=1):
            row = Word(
                word=word,
                meaning=f"v. 选项 {index}",
                example=f"We {word} the plan.",
                level=WordLevel.CET4,
                frequency=100 - index,
            )
            row.learning_state = LearningState(next_review_at=NOW + timedelta(days=20))
            session.add(row)


def test_acquisition_page_runs_all_three_stages_and_reloads_state(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    _add_distractors(database)
    page = AcquisitionPage(
        AcquisitionService(database, WordLevel.CET4),
        wordbook_service=WordbookService(database),
        mastery_service=MasteryService(database),
    )
    page.show()
    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.word_id == word_id
    assert page.current.proficiency_level == 0
    assert page.choice_widget.isVisible()
    assert page.english_choice_widget.isHidden()

    correct_index = next(
        index
        for index, option in enumerate(page.current.meaning_options)
        if option.is_correct
    )
    page.choice_widget.buttons[correct_index].click()
    _wait_until_idle(page, app)
    assert page.reveal_button.isVisible()
    page.reveal_button.click()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.proficiency_level == 1
    assert page.word_label.text() == ""
    assert page.current.word.casefold() not in page.answer_label.text().casefold()
    assert page.english_choice_widget.isVisible()

    correct_index = next(
        index
        for index, option in enumerate(page.current.cloze_options)
        if option.is_correct
    )
    page.english_choice_widget.buttons[correct_index].click()
    _wait_until_idle(page, app)
    page.reveal_button.click()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.proficiency_level == 2
    assert page.word_label.text() == ""
    assert page.spelling_panel.isVisible()

    page.self_confirm_button.click()
    _wait_until_idle(page, app)
    assert page.reveal_button.isVisible()
    page.reveal_button.click()
    _wait_until_idle(page, app)

    with database.session() as session:
        state = session.scalar(
            select(WordAcquisitionState).where(WordAcquisitionState.word_id == word_id)
        )
        assert state is not None
        assert state.proficiency_level == 3
        assert session.scalar(select(ReviewLog.id)) is None
    page.deleteLater()


def test_acquisition_card_transition_clears_embedded_assistant(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    _add_distractors(database)
    page = AcquisitionPage(
        AcquisitionService(database, WordLevel.CET4),
        assistant_service=AcquisitionAssistantService(),
    )
    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.assistant_panel is not None
    page.assistant_panel.transcript.setPlainText("旧单词对话")
    page.queue = [
        replace(
            page.current,
            word_id=page.current.word_id + 100,
            word="adopt",
            meaning="采用；收养",
        )
    ]

    page._show_next()

    assert page.current.word == "adopt"
    assert page.assistant_panel.transcript.toPlainText() == ""
    page.deleteLater()


def test_acquisition_assistant_starts_with_a_wider_sidebar(database) -> None:
    app = QApplication.instance() or QApplication([])
    page = AcquisitionPage(
        AcquisitionService(database, WordLevel.CET4),
        assistant_service=AcquisitionAssistantService(),
    )
    page.resize(1120, 720)
    page.show()
    app.processEvents()

    assert page.assistant_panel is not None
    assert page.workspace_splitter is not None
    assert page.assistant_panel.minimumWidth() == 340
    assert page.workspace_splitter.sizes()[1] >= 390
    page.close()
    page.deleteLater()


def test_acquisition_page_shows_group_boundary_before_next_released_group(
    database, word_id
) -> None:
    app = QApplication.instance() or QApplication([])
    with database.session() as session:
        state = session.scalar(
            select(WordAcquisitionState).where(WordAcquisitionState.word_id == word_id)
        )
        assert state is None
        session.add(WordAcquisitionState(word_id=word_id, proficiency_level=2))
        for index in range(10):
            word = Word(
                word=f"groupword{index}",
                meaning=f"组内释义 {index}",
                example=f"We groupword{index} the plan.",
                level=WordLevel.CET4,
                frequency=100 - index,
            )
            word.learning_state = LearningState(next_review_at=NOW - timedelta(days=1))
            word.acquisition_state = WordAcquisitionState(proficiency_level=2)
            session.add(word)

    page = AcquisitionPage(AcquisitionService(database, WordLevel.CET4))
    page.show()
    page.load_queue()
    _wait_until_idle(page, app)

    for _ in range(10):
        assert page.current is not None
        assert page.current.proficiency_level == 2
        page.self_confirm_button.click()
        _wait_until_idle(page, app)
        page.reveal_button.click()
        _wait_until_idle(page, app)

    assert page.current is None
    assert page.continue_button.text() == "开始下一组新词"
    assert page.continue_button.isEnabled()
    page.continue_button.click()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.proficiency_level == 2
    page.deleteLater()


def test_acquisition_page_unlocks_five_when_no_released_group_remains(
    database, word_id
) -> None:
    app = QApplication.instance() or QApplication([])
    with database.session() as session:
        session.add(WordAcquisitionState(word_id=word_id, proficiency_level=2))
        future = Word(
            word="futuregroup",
            meaning="未来组词",
            example="We futuregroup the items.",
            level=WordLevel.CET4,
            frequency=10,
        )
        future.learning_state = LearningState(next_review_at=NOW + timedelta(days=3))
        future.acquisition_state = WordAcquisitionState(proficiency_level=0)
        session.add(future)

    page = AcquisitionPage(AcquisitionService(database, WordLevel.CET4))
    page.show()
    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None
    page.self_confirm_button.click()
    _wait_until_idle(page, app)
    page.reveal_button.click()
    _wait_until_idle(page, app)

    assert page.current is None
    assert page.continue_button.text() == "继续学习 5 个新词"
    page.continue_button.click()
    _wait_until_idle(page, app)
    assert page.current is not None
    assert page.current.word == "futuregroup"
    page.deleteLater()


def test_acquisition_page_mastered_button_removes_card_and_persists(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    _add_distractors(database)
    mastery = MasteryService(database)
    page = AcquisitionPage(
        AcquisitionService(database, WordLevel.CET4),
        mastery_service=mastery,
    )
    page.show()
    page.load_queue()
    _wait_until_idle(page, app)
    assert page.mastered_button.isVisible()
    page.mastered_button.click()
    _wait_until_idle(page, app)
    assert page.current is None
    assert [item.word_id for item in mastery.list_mastered()] == [word_id]
    page.deleteLater()


def test_acquisition_page_content_error_offers_retry_without_advancing(
    database, word_id
) -> None:
    app = QApplication.instance() or QApplication([])
    page = AcquisitionPage(AcquisitionService(database, WordLevel.CET4))
    page.show()
    page.load_queue()
    _wait_until_idle(page, app)
    assert page.current is not None

    page._show_content_error("当前单词暂时无法生成学习题目。")
    assert page.reveal_button.text() == "重试加载当前词"
    page.reveal_button.click()
    _wait_until_idle(page, app)

    assert page.current is not None
    assert page.current.word_id == word_id
    assert page.current.proficiency_level == 0
    page.deleteLater()


def test_mastered_page_restores_selected_word(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    mastery = MasteryService(database)
    mastery.set_mastered(word_id, True)
    opened = []
    page = MasteredPage(mastery, on_open_word=opened.append)
    page.show()
    page.refresh()
    _wait_until_idle(page, app)
    assert page.word_list.count() == 1
    page.word_list.setCurrentRow(0)
    page.detail_button.click()
    assert [reference.word for reference in opened] == ["adapt"]
    page.restore_button.click()
    _wait_until_idle(page, app)
    assert page.word_list.count() == 0
    assert mastery.list_mastered() == []
    page.deleteLater()
