"""UI presentation tests for generated word learning-aid content."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.db.models import WordLearningAid
from app.services.review_service import ReviewService
from app.services.wordbook_service import WordbookService
from app.ui.review_page import ReviewPage
from app.ui.wordbook_page import WordbookPage


def _wait_until_idle(page, app: QApplication) -> None:
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()


def _add_aid(database, word_id: int) -> None:
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
                word_family_json=json.dumps(
                    [
                        {
                            "word": "adaptable",
                            "part_of_speech": "adj.",
                            "meaning": "适应性强的",
                            "relation": "derivative",
                        }
                    ],
                    ensure_ascii=False,
                ),
                generator="deepseek",
                model="deepseek-chat",
                prompt_version="word-learning-aids-v1",
                content_status="ai_generated_unreviewed",
                content_hash="abc",
            )
        )


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
    assert "待 AI 逐词生成并校验" not in page.collocations_label.text()
    page.deleteLater()


def test_review_page_keeps_placeholder_without_aid(database, word_id) -> None:
    app = QApplication.instance() or QApplication([])
    page = ReviewPage(ReviewService(database))

    page.load_queue()
    _wait_until_idle(page, app)
    page.reveal_answer()

    assert page.example_translation_label.text() == ""
    assert "待 AI 逐词生成并校验" in page.collocations_label.text()
    page.deleteLater()


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
    text = page.word_list.item(0).text()
    assert "学生适应新的环境。" in text
    page.deleteLater()
