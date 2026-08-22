"""Confusion graph summary and asynchronous AI explanations."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ai.schemas import ClusterAnalysisResult
from app.services.ai_service import AIService
from app.services.analysis_service import AnalysisService, ConfusionCluster
from app.ui.widgets.async_worker import AsyncWorker

logger = logging.getLogger(__name__)
_DEFAULT_STATUS = "关系由学习记录与确定性算法生成。"
ANALYSIS_OUTPUT_MAX_BLOCKS = 300


class AnalysisPage(QWidget):
    def __init__(self, service: AnalysisService, ai_service: AIService) -> None:
        super().__init__()
        self.service = service
        self.ai_service = ai_service
        self.clusters: list[ConfusionCluster] = []
        self.worker: AsyncWorker | None = None
        self.worker_action: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("你的常见混淆词")
        title.setObjectName("PageTitle")
        self.rebuild_button = QPushButton("重新分析")
        self.rebuild_button.setObjectName("PrimaryButton")
        self.rebuild_button.clicked.connect(self.rebuild)
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.rebuild_button)
        layout.addLayout(heading)
        self.status = QLabel(_DEFAULT_STATUS)
        self.status.setStyleSheet("color: #64748b;")
        layout.addWidget(self.status)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._selection_changed)
        self.list_widget.setStyleSheet(
            "QListWidget { background: white; border: 1px solid #e4e8ef; "
            "border-radius: 12px; padding: 8px; } "
            "QListWidget::item { padding: 14px; border-bottom: 1px solid #eef1f5; }"
            "QListWidget::item:selected { background: #eaf2ff; color: #1d4ed8; "
            "border: 1px solid #bfdbfe; border-radius: 8px; }"
        )
        layout.addWidget(self.list_widget)
        self.ai_button = QPushButton("AI 分析所选词簇")
        self.ai_button.setObjectName("PrimaryButton")
        self.ai_button.setEnabled(False)
        self.ai_button.clicked.connect(self.analyze_selected)
        layout.addWidget(self.ai_button)
        self.ai_output = QTextEdit()
        self.ai_output.setReadOnly(True)
        self.ai_output.document().setMaximumBlockCount(ANALYSIS_OUTPUT_MAX_BLOCKS)
        self.ai_output.setPlaceholderText(
            "选择词簇后，可让本地模型解释易混原因并生成练习。"
        )
        self.ai_output.setMinimumHeight(190)
        layout.addWidget(self.ai_output)
        self.refresh()

    def refresh(self) -> bool:
        self.list_widget.clear()
        self.ai_output.clear()
        try:
            self.clusters = self.service.get_clusters()
        except Exception:
            logger.exception("Could not load confusion clusters")
            self.clusters = []
            self.status.setText("暂时无法读取错词关系，请稍后重试。")
            self.ai_button.setEnabled(False)
            return False
        self.status.setText(_DEFAULT_STATUS)
        if not self.clusters:
            self.list_widget.addItem(
                "还没有足够的错词数据。可先运行 demo 数据脚本体验。"
            )
            self.ai_button.setEnabled(False)
            return True
        for cluster in self.clusters:
            self.list_widget.addItem(
                f"Cluster #{cluster.cluster_number}    {'  ↔  '.join(cluster.words)}\n"
                f"相关度 {cluster.average_score:.2f} · {cluster.relation_type.value}"
            )
        return True

    def rebuild(self) -> None:
        if self.worker is not None:
            return
        self._set_busy(True)
        self.status.setText("正在计算候选与关系…")
        self.worker_action = "rebuild"
        self.worker = AsyncWorker(self.service.rebuild_confusion_graph, parent=self)
        self.worker.result_ready.connect(self._rebuild_finished)
        self.worker.failed.connect(self._show_failure)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _rebuild_finished(self, result) -> None:
        if self.refresh():
            self.status.setText(
                f"候选 {result.candidate_count} · 关系 {result.edge_count} · "
                f"词簇 {result.cluster_count}"
            )

    def _selection_changed(self, row: int) -> None:
        self.ai_button.setEnabled(0 <= row < len(self.clusters) and self.worker is None)

    def analyze_selected(self) -> None:
        row = self.list_widget.currentRow()
        if self.worker is not None or not (0 <= row < len(self.clusters)):
            return
        self._set_busy(True)
        self.ai_output.setPlainText("正在调用本地模型…")
        self.worker_action = "analysis"
        self.worker = AsyncWorker(
            self.ai_service.analyze_cluster,
            self.clusters[row],
            parent=self,
        )
        self.worker.result_ready.connect(self._show_analysis)
        self.worker.failed.connect(self._show_failure)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _show_analysis(self, result: ClusterAnalysisResult) -> None:
        analysis = result.analysis
        sections = [analysis.summary, f"易混原因：{analysis.confusion_reason}"]
        for item in analysis.word_explanations:
            sections.append(
                f"{item.word}：{item.meaning}\n用法：{item.usage}\n"
                f"记忆：{item.memory_tip}\n例句：{item.example}"
            )
        exercise = analysis.exercise
        sections.append(
            f"练习：{exercise.question}\n"
            + "\n".join(exercise.options)
            + f"\n答案：{exercise.answer}\n{exercise.explanation}"
        )
        cache_note = "缓存" if result.cached else "新生成"
        sections.append(
            f"模型：{result.model} · {cache_note} · 置信度 {result.confidence:.0%}"
        )
        self.ai_output.setPlainText("\n\n".join(sections))

    def _show_failure(self, message: str) -> None:
        logger.error("Analysis page task failed: %s", message)
        if self.worker_action == "rebuild":
            self.status.setText(f"重新分析失败：{message}")
        else:
            self.ai_output.setPlainText(f"暂时无法完成：{message}")

    def _set_busy(self, busy: bool) -> None:
        self.rebuild_button.setEnabled(not busy)
        self.ai_button.setEnabled(
            not busy and 0 <= self.list_widget.currentRow() < len(self.clusters)
        )

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.worker_action = None
        self._set_busy(False)
