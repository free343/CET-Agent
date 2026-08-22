from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.db.models import RelationType
from app.services.analysis_service import ConfusionCluster
from app.ui.analysis_page import AnalysisPage


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
