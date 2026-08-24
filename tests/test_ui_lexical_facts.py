"""Dynamic lexical-fact section composition and answer gating tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

from PySide6.QtWidgets import QApplication

from app.db.models import WordLexicalFact
from app.services.lexical_fact_view import (
    LexicalFactSection,
    build_lexical_facts_view,
)
from app.services.review_service import ReviewService
from app.ui.review_page import ReviewPage
from app.ui.widgets.review_card import ReviewCardWidget


def _card() -> ReviewCardWidget:
    no_op = lambda *_args: None
    return ReviewCardWidget(
        on_reveal=no_op,
        on_unlock=no_op,
        on_undo=no_op,
        on_favorite=no_op,
        on_choice=no_op,
        on_rating=no_op,
    )


def _section(key: str, title: str, *, verified: bool = True) -> LexicalFactSection:
    return LexicalFactSection(
        key=key,
        title=title,
        items=(f"{title} 内容",),
        status="已验证" if verified else "AI · 未审核",
        verified=verified,
    )


def test_empty_dynamic_projection_hides_entire_fact_frame() -> None:
    _app = QApplication.instance() or QApplication([])
    card = _card()
    card.show_learning_aids((), (), has_learning_aid=False, lexical_sections=())
    assert card.learning_aids_frame.isHidden()
    assert not card._learning_aid_groups["forms"].isVisible()
    card.deleteLater()


def test_dynamic_projection_has_no_empty_group_for_one_section() -> None:
    app = QApplication.instance() or QApplication([])
    card = _card()
    card.show_learning_aids(
        (),
        (),
        has_learning_aid=False,
        lexical_sections=(_section("forms", "词形"),),
    )
    card.show()
    app.processEvents()
    assert card.learning_aids_frame.isVisible()
    assert card._learning_aid_groups["forms"].isVisible()
    assert not card._learning_aid_groups["collocations"].isVisible()
    assert not card._learning_aid_groups["relations"].isVisible()
    assert not card._learning_aid_groups["derivatives"].isVisible()
    card.deleteLater()


def test_dynamic_projection_supports_all_four_sections_and_line_breaks() -> None:
    app = QApplication.instance() or QApplication([])
    card = _card()
    sections = (
        _section("forms", "词形"),
        _section("collocations", "搭配", verified=False),
        _section("relations", "近反义"),
        _section("derivatives", "派生词", verified=False),
    )
    card.show_learning_aids(
        (),
        (),
        has_learning_aid=True,
        feedback_enabled=True,
        lexical_sections=sections,
    )
    card.show()
    app.processEvents()
    assert all(group.isVisible() for group in card._learning_aid_groups.values())
    assert card.learning_aid_report_button.isVisible()
    assert card.learning_aid_status_label.text() == "AI · 未审核"
    card.deleteLater()


def test_review_assistant_receives_facts_only_after_answer_boundary(
    database,
    word_id,
) -> None:
    app = QApplication.instance() or QApplication([])
    with database.session() as session:
        session.add(
            WordLexicalFact(
                word_id=word_id,
                forms_json=json.dumps(
                    [
                        {
                            "paradigm_type": "degree",
                            "part_of_speech": "adjective",
                            "gradability": "contextual",
                            "forms": [{"role": "superlative", "value": "least"}],
                        }
                    ]
                ),
                relations_json="[]",
                forms_status="source_validated",
                relations_status="missing",
                source="fixture",
                content_hash="0" * 64,
            )
        )
    page = ReviewPage(ReviewService(database))
    page.load_queue()
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()
    before = page._assistant_context()
    assert before is not None
    assert "词形=" not in before.content
    page.reveal_answer()
    after = page._assistant_context()
    assert after is not None
    assert "词形=" in after.content
    assert "least" in after.content
    page.deleteLater()


def test_source_candidate_relations_are_visible_with_pending_trust(
    database, word_id
) -> None:
    with database.session() as session:
        session.add(
            WordLexicalFact(
                word_id=word_id,
                forms_json="[]",
                relations_json="[]",
                forms_status="missing",
                relations_status="missing",
                source="fixture",
                content_hash="0" * 64,
                candidate_relations_json=json.dumps(
                    [
                        {
                            "relation_type": "synonym",
                            "synset_id": "syn-adapt",
                            "ili": "i-adapt",
                            "part_of_speech": "verb",
                            "sense": "适应",
                            "items": [
                                {
                                    "word": "adjust",
                                    "meaning": "调整；适应",
                                    "english_definition": "change to fit",
                                    "frequency": 100,
                                    "evidence": [
                                        {
                                            "source_id": "oewn-2025",
                                            "source_version": "2025",
                                            "field": "synset.members",
                                            "locator": "synset=syn-adapt",
                                            "source_sha256": "b" * 64,
                                        },
                                        {
                                            "source_id": "omw-cmn-2",
                                            "source_version": "2.0",
                                            "field": "synset.labels",
                                            "locator": "ili=i-adapt",
                                            "source_sha256": "c" * 64,
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                    ensure_ascii=False,
                ),
                candidate_status="candidate_only",
                candidate_source="wordnet-cow-relation-candidates-v2",
                candidate_content_hash="a" * 64,
            )
        )
    with database.session() as session:
        fact = session.get(WordLexicalFact, word_id)
        assert fact is not None
        view = build_lexical_facts_view(fact, None)
    relations = next(section for section in view.sections if section.key == "relations")
    assert relations.items == ("近义：adjust v. 调整；适应",)
    assert relations.status == "来源候选 · 待审核"
    assert relations.verified is False
    assert relations.reportable is False


def test_formal_relation_display_omits_current_word_context(database, word_id) -> None:
    with database.session() as session:
        session.add(
            WordLexicalFact(
                word_id=word_id,
                forms_json="[]",
                relations_json=json.dumps(
                    [
                        {
                            "relation_type": "synonym",
                            "part_of_speech": "adjective",
                            "sense": "当前词义项",
                            "items": [
                                {
                                    "word": "primary",
                                    "meaning": "主要的",
                                    "note": "不在关系行中展示注释",
                                }
                            ],
                        }
                    ],
                    ensure_ascii=False,
                ),
                forms_status="missing",
                relations_status="source_validated",
                source="fixture",
                content_hash="0" * 64,
            )
        )
    with database.session() as session:
        fact = session.get(WordLexicalFact, word_id)
        assert fact is not None
        view = build_lexical_facts_view(fact, None)
    relations = next(section for section in view.sections if section.key == "relations")
    assert relations.items == ("近义：primary adj. 主要的",)
    assert "当前词义项" not in relations.items[0]
