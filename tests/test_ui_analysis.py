from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ai.schemas import (
    ClusterAnalysis,
    ClusterAnalysisResult,
    Exercise,
    WordExplanation,
)
from app.db.models import RelationType
from app.services.analysis_service import ConfusionCluster
from app.ui.analysis_page import ANALYSIS_OUTPUT_MAX_BLOCKS, AnalysisPage


class FakeAnalysisService:
    @staticmethod
    def get_clusters() -> list[ConfusionCluster]:
        return [
            ConfusionCluster(
                cluster_number=1,
                word_ids=(1, 2),
                words=("adapt", "adopt"),
                error_counts=(2, 2),
                relation_type=RelationType.SPELLING,
                average_score=0.8,
            )
        ]


def test_selected_cluster_has_explicit_readable_style() -> None:
    app = QApplication.instance() or QApplication([])
    page = AnalysisPage(FakeAnalysisService(), object())
    page.list_widget.setCurrentRow(0)
    app.processEvents()

    assert page.list_widget.currentItem().text()
    assert "QListWidget::item:selected" in page.list_widget.styleSheet()
    assert "color: #1d4ed8" in page.list_widget.styleSheet()
    page.deleteLater()


def test_selected_cluster_can_start_bounded_practice() -> None:
    app = QApplication.instance() or QApplication([])
    started: list[tuple[tuple[int, ...], str]] = []
    page = AnalysisPage(
        FakeAnalysisService(),
        object(),
        on_start_practice=lambda word_ids, label: started.append((word_ids, label)),
    )
    page.list_widget.setCurrentRow(0)
    app.processEvents()

    assert page.practice_button.isEnabled()
    page.practice_button.click()
    app.processEvents()

    assert started == [((1, 2), "adapt / adopt")]
    page.deleteLater()


def test_selected_cluster_exposes_each_word_card_entry() -> None:
    app = QApplication.instance() or QApplication([])
    opened = []
    page = AnalysisPage(
        FakeAnalysisService(),
        object(),
        on_open_word=opened.append,
    )
    page.list_widget.setCurrentRow(0)
    app.processEvents()

    assert page.word_detail_layout.count() == 3
    page.word_detail_layout.itemAt(0).widget().click()
    assert [reference.word for reference in opened] == ["adapt"]
    page.deleteLater()


def test_refresh_clears_stale_analysis_and_error_status() -> None:
    app = QApplication.instance() or QApplication([])
    page = AnalysisPage(FakeAnalysisService(), object())
    page.ai_output.setPlainText("stale model output")
    page.status.setText("previous failure")

    assert page.refresh() is True
    app.processEvents()

    assert page.ai_output.toPlainText() == ""
    assert page.status.text() == "关系由学习记录与确定性算法生成。"
    page.deleteLater()


def test_analysis_output_has_bounded_document_blocks() -> None:
    app = QApplication.instance() or QApplication([])
    page = AnalysisPage(FakeAnalysisService(), object())

    for index in range(ANALYSIS_OUTPUT_MAX_BLOCKS + 20):
        page.ai_output.append(f"line-{index}")
    app.processEvents()

    assert page.ai_output.document().blockCount() <= ANALYSIS_OUTPUT_MAX_BLOCKS
    assert "line-0" not in page.ai_output.toPlainText()
    page.deleteLater()


def test_analysis_output_does_not_render_internal_confidence() -> None:
    _app = QApplication.instance() or QApplication([])
    page = AnalysisPage(FakeAnalysisService(), object())
    result = ClusterAnalysisResult(
        analysis=ClusterAnalysis(
            summary="总结",
            confusion_reason="原因",
            word_explanations=[
                WordExplanation(
                    word="adapt",
                    meaning="适应",
                    usage="adapt to",
                    memory_tip="结合例句",
                    example="We adapt to change.",
                )
            ],
            exercise=Exercise(
                question="选择正确单词",
                options=["adapt", "adopt"],
                answer="adapt",
                explanation="adapt to 表示适应",
            ),
        ),
        confidence=0.97,
        model="fake-model",
    )

    page._show_analysis(result)

    output = page.ai_output.toPlainText()
    assert "模型：fake-model · 新生成" in output
    assert "置信度" not in output
    assert "97%" not in output
    page.deleteLater()
