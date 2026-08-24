"""Read-only linked-word detail service and widget regression tests."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.db.models import Word, WordLearningAid, WordLevel, WordLexicalFact
from app.services.lexical_fact_view import LexicalFactSection, LinkedWordReference
from app.services.word_detail_service import WordDetailService, WordDetailView
from app.ui.widgets.lexical_link_label import LexicalLinkLabel
from app.ui.widgets.review_card import ReviewCardWidget
from app.ui.word_detail_controller import WordDetailController
from app.ui.word_detail_dialog import WordDetailDialog


def test_word_lookup_prioritizes_exact_headword_and_bounds_invalid_input(
    database,
    word_id,
) -> None:
    with database.session() as session:
        for word in ("adaptation", "adapter"):
            session.add(
                Word(
                    word=word,
                    meaning="相关词",
                    level=WordLevel.CET4,
                )
            )

    service = WordDetailService(database)
    results = service.search_words("  ADAPT ", limit=2)

    assert [item.word for item in results] == ["adapt", "adaptation"]
    assert results[0].word_id == word_id
    assert results[0].reference.word == "adapt"
    assert service.search_words("adapt?", limit=10) == []
    assert service.search_words("", limit=10) == []


def test_in_bank_detail_reuses_word_and_linked_fact_projection(
    database, word_id
) -> None:
    with database.session() as session:
        session.add(
            WordLearningAid(
                word_id=word_id,
                example="Students adapt to change.",
                example_translation="学生适应变化。",
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
                        }
                    ],
                    ensure_ascii=False,
                ),
            )
        )
        session.add(
            WordLexicalFact(
                word_id=word_id,
                forms_json="[]",
                relations_json=json.dumps(
                    [
                        {
                            "relation_type": "synonym",
                            "part_of_speech": "verb",
                            "sense": "适应",
                            "items": [{"word": "adjust", "meaning": "调整；适应"}],
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

    service = WordDetailService(database)
    view = service.get_word_detail(
        LinkedWordReference(word="adapt", trust="source_validated")
    )

    assert view.reference_only is False
    assert view.word == "adapt"
    assert view.meaning == "适应；改编"
    assert view.example_translation == "学生适应变化。"
    relations = next(section for section in view.sections if section.key == "relations")
    assert relations.items == ("近义：adjust v. 调整；适应",)
    assert relations.reference_for(0) is not None
    assert relations.reference_for(0).word == "adjust"
    assert relations.reference_for(0).trust == "source_validated"
    assert relations.reference_for(0).origin_word == "adapt"
    assert relations.reference_for(0).origin_meaning == "适应；改编"
    assert relations.reference_for(0).origin_relation == "近义"
    derivatives = next(
        section for section in view.sections if section.key == "derivatives"
    )
    assert derivatives.reference_for(0).word == "adaptable"


def test_outside_bank_detail_is_reference_only_and_does_not_insert_word(
    database,
) -> None:
    service = WordDetailService(database)
    view = service.get_word_detail(
        LinkedWordReference(
            word="major",
            part_of_speech="adj.",
            meaning="主要的",
            english_definition="greater in importance",
            trust="source_candidate",
        )
    )

    assert view.reference_only is True
    assert view.word == "major"
    assert view.meaning == "adj. 主要的"
    assert view.trust_label == "来源候选 · 待审核 · 词库外参考"
    assert view.reference.english_definition == "greater in importance"
    assert view.sections == ()
    with database.session() as session:
        assert session.query(WordLearningAid).count() == 0


def test_invalid_detail_target_is_rejected_without_database_access(database) -> None:
    service = WordDetailService(database)
    try:
        service.get_word_detail(LinkedWordReference(word="not a word"))
    except ValueError as exc:
        assert "格式" in str(exc)
    else:  # pragma: no cover - assertion is the failure signal
        raise AssertionError("unsafe linked targets must be rejected")


def test_lexical_link_label_emits_only_registered_local_reference() -> None:
    _app = QApplication.instance() or QApplication([])
    reference = LinkedWordReference(
        word="major",
        part_of_speech="adj.",
        meaning="主要的",
    )
    label = LexicalLinkLabel()
    emitted: list[LinkedWordReference] = []
    label.linked_word_clicked.connect(emitted.append)
    label.set_items(("近义：major adj. 主要的",), (reference,))

    assert '<a href="word:major"' in label.text()
    label._link_activated("word:major")
    assert emitted == [reference]
    label._link_activated("https://example.com")
    assert emitted == [reference]
    label.deleteLater()


def test_word_detail_dialog_shows_origin_comparison_and_keeps_keyboard_focus() -> None:
    _app = QApplication.instance() or QApplication([])
    dialog = WordDetailDialog()
    reference = LinkedWordReference(
        word="major",
        meaning="主要的",
        origin_word="main",
        origin_meaning="主要的；核心的",
        origin_relation="近义",
    )
    dialog.set_view(
        WordDetailView(
            reference=reference,
            word="major",
            phonetic="/ˈmeɪdʒər/",
            meaning="主要的",
            level="CET4",
            example="",
            example_translation="",
            sections=(
                LexicalFactSection(
                    key="relations",
                    title="近反义",
                    items=("近义：main adj. 主要的",),
                    status="已验证",
                    verified=True,
                    item_references=(
                        LinkedWordReference(word="main", meaning="主要的"),
                    ),
                ),
            ),
        ),
        can_go_back=True,
    )
    dialog.show()
    _app.processEvents()

    assert dialog.comparison_frame.isHidden() is False
    assert "main" in dialog.origin_word_label.text()
    assert dialog.back_button.isVisible()
    dialog._focus_link("main")
    assert dialog.focusWidget() is not None
    dialog.close()
    dialog.deleteLater()


def test_review_card_passes_linked_target_to_study_page_callback() -> None:
    _app = QApplication.instance() or QApplication([])
    reference = LinkedWordReference(word="major", meaning="主要的")
    emitted: list[LinkedWordReference] = []
    no_op = lambda *_args: None
    card = ReviewCardWidget(
        on_reveal=no_op,
        on_unlock=no_op,
        on_undo=no_op,
        on_favorite=no_op,
        on_choice=no_op,
        on_rating=no_op,
        on_linked_word=emitted.append,
    )
    card.show_learning_aids(
        (),
        (),
        has_learning_aid=False,
        lexical_sections=(
            LexicalFactSection(
                key="relations",
                title="近反义",
                items=("近义：major adj. 主要的",),
                status="来源候选 · 待审核",
                verified=False,
                reportable=False,
                item_references=(reference,),
            ),
        ),
    )
    card.relations_label._link_activated("word:major")
    assert emitted == [reference]
    card.deleteLater()


def test_detail_controller_ignores_result_from_previous_generation() -> None:
    app = QApplication.instance() or QApplication([])

    class FakeService:
        @staticmethod
        def get_word_detail(reference: LinkedWordReference) -> WordDetailView:
            return WordDetailView(
                reference=reference,
                word=reference.word,
                phonetic="",
                meaning=reference.meaning,
                level="CET4",
                example="",
                example_translation="",
                sections=(),
            )

    controller = WordDetailController(FakeService())
    first = LinkedWordReference(word="adapt", meaning="适应")
    second = LinkedWordReference(word="major", meaning="主要的")
    controller.open(first)
    first_worker = controller.worker
    assert first_worker is not None
    controller._start(second)
    controller._loaded(1, FakeService.get_word_detail(first))
    assert controller.dialog.word_label.text() == "major"
    for worker in (first_worker, controller.worker):
        if worker is not None:
            worker.wait(2_000)
    app.processEvents()
    assert first_worker.parent() is None
    assert controller.worker is None
    controller.close()
    controller.dialog.deleteLater()
