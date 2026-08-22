"""Read-only first-version configuration overview."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QVBoxLayout, QWidget

from app.config import Settings


class SettingsPage(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(24, 22, 24, 22)
        form.addRow("LLM Provider", QLabel(settings.llm_provider))
        form.addRow("本地模型", QLabel(settings.llm_model))
        form.addRow("服务地址", QLabel(settings.llm_base_url))
        form.addRow("Embedding Provider", QLabel(settings.embedding_provider))
        form.addRow("Embedding 地址", QLabel(settings.embedding_base_url))
        form.addRow("Embedding 模型", QLabel(settings.embedding_model))
        form.addRow("混淆阈值", QLabel(f"{settings.confusion_threshold:.2f}"))
        form.addRow(
            "提醒时段",
            QLabel(
                f"{settings.reminder_start_time:%H:%M} – "
                f"{settings.reminder_end_time:%H:%M}"
            ),
        )
        layout.addWidget(card)
        note = QLabel("第一版通过项目根目录的 .env 修改设置；API key 不会显示或写入日志。")
        note.setStyleSheet("color: #64748b;")
        layout.addWidget(note)
        layout.addStretch()
