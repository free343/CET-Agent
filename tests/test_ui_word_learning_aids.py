"""UI presentation tests for generated word learning-aid content."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QBoxLayout, QInputDialog

from app.db.models import LearningAidIssueType, WordLearningAid
from app.services.learning_aid_feedback_service import LearningAidFeedbackService
from app.services.review_service import ReviewService
from app.services.wordbook_service import WordbookService
from app.ui.review_page import ReviewPage
from app.ui.widgets.review_card import ReviewCardWidget
from app.ui.wordbook_page import WordbookPage


def _wait_until_idle(page, app: QApplication) -> None:
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()


def _add_aid(database, word_id: int, *, word_family: list[dict] | None = None) -> None:
    if word_family is None:
        word_family = [
            {
                "word": "adaptable",
                "part_of_speech": "adj.",
                "meaning": "适应性强的",
                "relation": "derivative",
            }
        ]
    with database.session() as session:
        session.add(
            WordLearningAid(
                word_id=word_id,
                example="Students adapt to new environments.",
                example_translation="学生适应新的环境。",
                collocations_json=json.dumps(
                    [{"phrase": "adapt to", "meaning": "适应"}],
                    ensure_ascii=False,
                ),
                word_family_json=json.dumps(word_family, ensure_ascii=False),
                generator="deepseek",
                model="deepseek-chat",
                prompt_version="word-learning-aids-v1",
                content_status="ai_generated_unreviewed",
                content_hash="abc",
            )
        )


def test_review_card_separates_multiple_learning_aids_with_newlines() -> None:
    assert ReviewCardWidget._format_learning_aids(
        ("adapt to｜适应", "adapt from｜改编自")
    ) == ("adapt to｜适应\nadapt from｜改编自")


def test_review_page_renders_generated_aids(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    _add_aid(database, word_id)
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    page.reveal_answer()

    assert "adapt to｜适应" in page.collocations_label.text()
    assert "adaptable (adj.)｜适应性强的" in page.word_family_label.text()
    assert page.example_translation_label.text() == "学生适应新的环境。"
    assert page.learning_aid_status_label.text() == "AI · 未审核"
    assert "尚未人工审核" in page.learning_aid_status_label.toolTip()
    assistant_context = page._assistant_context()
    assert assistant_context is not None
    assert "collocations=adapt to｜适应" in assistant_context.content
    assert "word_family=adaptable (adj.)｜适应性强的" in assistant_context.content
    page.deleteLater()


def test_valid_empty_word_family_is_not_presented_as_pending(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    _add_aid(database, word_id, word_family=[])
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    page.reveal_answer()

    assert page.current is not None
    assert page.current.has_learning_aid is True
    assert page.word_family_label.text() == "暂无可靠的同族 / 派生词"
    assert "待 AI" not in page.word_family_label.text()
    page.deleteLater()


def test_review_page_keeps_placeholder_without_aid(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    page.reveal_answer()

    assert page.example_translation_label.text() == ""
    assert page.collocations_label.text() == "内容尚未生成"
    assert page.word_family_label.text() == "内容尚未生成"
    assert page.learning_aid_report_button.isHidden() is True
    page.deleteLater()


def test_review_page_records_learning_aid_issue(
    database,
    word_id,
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    _add_aid(database, word_id)
    feedback_service = LearningAidFeedbackService(database)
    page = ReviewPage(
        ReviewService(database),
        learning_aid_feedback_service=feedback_service,
    )
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        staticmethod(lambda *_args, **_kwargs: ("中文翻译不准确", True)),
    )

    page.load_queue()
    _wait_until_idle(page, app)
    page.reveal_answer()
    page.learning_aid_report_button.click()
    _wait_until_idle(page, app)

    assert page.current is not None
    assert (
        page.current.learning_aid_feedback
        is LearningAidIssueType.TRANSLATION_INACCURATE
    )
    assert page.learning_aid_status_label.text() == "AI · 已反馈"
    assert "已记录你的问题反馈" in page.learning_aid_status_label.toolTip()
    page.deleteLater()


def test_learning_aid_columns_stack_on_narrow_review_card() -> None:
    app = QApplication.instance() or QApplication([])
    no_op = lambda *_args: None
    card = ReviewCardWidget(
        on_reveal=no_op,
        on_unlock=no_op,
        on_undo=no_op,
        on_favorite=no_op,
        on_choice=no_op,
        on_rating=no_op,
    )
    card.show()

    card.resize(560, 700)
    app.processEvents()
    assert (
        card.learning_aids_content_layout.direction()
        is QBoxLayout.Direction.TopToBottom
    )

    card.resize(800, 700)
    card.show_learning_aids(
        ("adapt to｜适应",),
        ("adaptable (adj.)｜适应性强的",),
        has_learning_aid=True,
    )
    app.processEvents()
    assert (
        card.learning_aids_content_layout.direction()
        is QBoxLayout.Direction.LeftToRight
    )
    assert card.learning_aids_scroll.verticalScrollBar().maximum() == 0
    card.deleteLater()


def test_generated_aid_review_state_is_a_compact_single_line_badge() -> None:
    app = QApplication.instance() or QApplication([])
    no_op = lambda *_args: None
    card = ReviewCardWidget(
        on_reveal=no_op,
        on_rating=no_op,
        on_choice=no_op,
        on_unlock=no_op,
        on_favorite=no_op,
        on_undo=no_op,
        on_report_learning_aid=no_op,
    )
    card.resize(340, 420)
    card.show_learning_aids(
        ("adapt to｜适应",),
        ("adaptable (adj.)｜适应性强的",),
        has_learning_aid=True,
        feedback_enabled=True,
    )
    card.show()
    app.processEvents()

    assert card.learning_aid_status_label.wordWrap() is False
    assert card.learning_aid_status_label.text() == "AI · 未审核"
    assert "AI 生成" in card.learning_aid_status_label.toolTip()
    assert "尚未人工审核" in card.learning_aid_status_label.toolTip()
    assert (
        card.learning_aid_status_label.sizeHint().height()
        <= card.learning_aid_report_button.sizeHint().height()
    )
    card.deleteLater()


def test_long_learning_aids_have_vertical_scroll_range_on_narrow_card() -> None:
    app = QApplication.instance() or QApplication([])
    no_op = lambda *_args: None
    card = ReviewCardWidget(
        on_reveal=no_op,
        on_unlock=no_op,
        on_undo=no_op,
        on_favorite=no_op,
        on_choice=no_op,
        on_rating=no_op,
    )
    long_collocations = tuple(
        f"adapt to a demanding situation {index}｜适应一个需要详细说明的复杂情境"
        for index in range(4)
    )
    long_family = tuple(
        f"adaptability{index} (n.)｜在不同环境中灵活调整并保持有效的能力"
        for index in range(4)
    )
    card.resize(800, 420)
    card.show_learning_aids(
        long_collocations,
        long_family,
        has_learning_aid=True,
    )
    card.show()
    app.processEvents()
    card.resize(560, 420)
    app.processEvents()

    scroll_bar = card.learning_aids_scroll.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    assert (
        card.learning_aids_scroll.verticalScrollBarPolicy()
        is Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    center = card.learning_aids_scroll.viewport().rect().center()
    wheel_event = QWheelEvent(
        QPointF(center),
        QPointF(card.learning_aids_scroll.viewport().mapToGlobal(center)),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(card.learning_aids_scroll.viewport(), wheel_event)
    app.processEvents()
    assert scroll_bar.value() > 0
    card.deleteLater()


def test_wordbook_page_renders_generated_example_and_translation(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    _add_aid(database, word_id)
    service = WordbookService(database)
    service.set_favorite(word_id, True)
    page = WordbookPage(service)

    page.refresh()
    _wait_until_idle(page, app)

    assert page.word_list.count() == 1
    text = str(page.word_list.item(0).data(Qt.ItemDataRole.AccessibleTextRole) or "")
    assert "学生适应新的环境。" in text
    page.deleteLater()
