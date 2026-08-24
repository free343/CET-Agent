"""Read-only configuration overview with an actionable advanced-model guide."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.config import ENV_FILE, Settings
from app.ui.widgets.pronunciation_widgets import PronunciationInstallButton

DEEPSEEK_ADVANCED_TEMPLATE = """ADVANCED_LLM_PROVIDER=openai-compatible
ADVANCED_LLM_MODEL=deepseek-v4-flash
ADVANCED_LLM_BASE_URL=https://api.deepseek.com
ADVANCED_LLM_API_KEY="""


class SettingsPage(QWidget):
    def __init__(
        self,
        settings: Settings,
        pronunciation_player: object | None = None,
    ) -> None:
        super().__init__()
        self.pronunciation_player = pronunciation_player
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(24, 22, 24, 22)
        form.addRow("学习级别", QLabel(settings.study_level))
        form.addRow("LLM Provider", QLabel(settings.llm_provider))
        form.addRow("本地模型", QLabel(settings.llm_model))
        form.addRow("服务地址", QLabel(settings.llm_base_url))
        advanced_enabled = bool(settings.advanced_llm_provider)
        advanced_model = settings.advanced_llm_model or "未启用"
        advanced_status = "已启用" if advanced_enabled else "未启用"
        status_label = QLabel(advanced_status)
        status_label.setObjectName("AdvancedModelStatus")
        form.addRow("高级通道状态", status_label)
        form.addRow(
            "高级 Provider",
            QLabel(settings.advanced_llm_provider or "未配置"),
        )
        form.addRow("高级模型", QLabel(advanced_model))
        form.addRow(
            "高级服务地址",
            QLabel(settings.advanced_llm_base_url or "未配置"),
        )
        if settings.advanced_llm_provider.strip().lower().replace("_", "-") == "ollama":
            credential_status = "本地 Ollama 无需 API key"
        elif settings.advanced_llm_api_key:
            credential_status = "已配置（内容已隐藏）"
        else:
            credential_status = "未配置"
        form.addRow("高级凭据", QLabel(credential_status))
        form.addRow("Embedding Provider", QLabel(settings.embedding_provider))
        form.addRow("Embedding 地址", QLabel(settings.embedding_base_url))
        form.addRow("Embedding 模型", QLabel(settings.embedding_model))
        form.addRow("混淆阈值", QLabel(f"{settings.confusion_threshold:.2f}"))
        form.addRow("每日新词释放", QLabel(f"{settings.daily_new_word_limit} 个"))
        form.addRow("新词学习组大小", QLabel(f"{settings.new_word_group_size} 个"))
        form.addRow("主动加练包大小", QLabel(f"{settings.extra_new_word_count} 个"))
        pronunciation_row = QHBoxLayout()
        self.pronunciation_status_label = QLabel("")
        self.pronunciation_status_label.setObjectName("PronunciationStatus")
        pronunciation_row.addWidget(self.pronunciation_status_label, 1)
        pronunciation_row.addWidget(
            PronunciationInstallButton(pronunciation_player, self)
        )
        pronunciation_container = QWidget()
        pronunciation_container.setLayout(pronunciation_row)
        form.addRow("英语发音", pronunciation_container)
        pronunciation_note = QLabel(
            "未检测到英语声音时，点击按钮打开 Windows 语言设置，添加 English 语言并在"
            "语言选项中下载语音包；安装后返回应用即可自动重新检测。"
        )
        pronunciation_note.setWordWrap(True)
        pronunciation_note.setObjectName("PronunciationSetupNote")
        form.addRow("", pronunciation_note)
        form.addRow(
            "提醒时段",
            QLabel(
                f"{settings.reminder_start_time:%H:%M} – "
                f"{settings.reminder_end_time:%H:%M}"
            ),
        )
        layout.addWidget(card)

        workload_note = QLabel(
            "学习负载设置只影响尚未开始的工作：每日释放值仅在某个 CET 等级首次启用时"
            "用于排期；组大小和主动加练包大小用于后续批次。已复习、已毕业、收藏和"
            "完全掌握状态不会被设置项重新排序或重置。修改 .env 后需重启应用。"
        )
        workload_note.setWordWrap(True)
        workload_note.setObjectName("SettingsWorkloadNote")
        layout.addWidget(workload_note)

        advanced_card = QFrame()
        advanced_card.setObjectName("Card")
        advanced_layout = QVBoxLayout(advanced_card)
        advanced_layout.setContentsMargins(24, 22, 24, 22)
        advanced_layout.setSpacing(10)
        advanced_title = QLabel("高级模型配置通道")
        advanced_title.setStyleSheet("font-weight: 700; color: #1e293b;")
        advanced_layout.addWidget(advanced_title)
        guide = QLabel(
            "编辑下面路径中的 .env，保存后重启应用。DeepSeek 可直接复用同一文件中"
            "已有的 DEEPSEEK_API_KEY；其他兼容接口请填写 ADVANCED_LLM_API_KEY。"
        )
        guide.setWordWrap(True)
        advanced_layout.addWidget(guide)
        path_label = QLabel(str(ENV_FILE))
        path_label.setObjectName("AdvancedConfigPath")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setStyleSheet("color: #4338ca;")
        advanced_layout.addWidget(path_label)
        template = QPlainTextEdit()
        template.setObjectName("AdvancedConfigTemplate")
        template.setReadOnly(True)
        template.setPlainText(DEEPSEEK_ADVANCED_TEMPLATE)
        template.setMaximumHeight(118)
        advanced_layout.addWidget(template)
        restart_note = QLabel(
            "重启后，AI 助手输入框上方会提供“自动选择 / 本地模型 / 高级模型”三档。"
            "高级模型可能产生网络流量和 API 费用，只会在用户明确选择或确认后调用。"
        )
        restart_note.setWordWrap(True)
        restart_note.setStyleSheet("color: #64748b;")
        advanced_layout.addWidget(restart_note)
        layout.addWidget(advanced_card)

        note = QLabel("API key 不会显示在此页面，也不会写入日志。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b;")
        layout.addWidget(note)
        layout.addStretch()
        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        self._update_pronunciation_status(getattr(pronunciation_player, "status", None))
        signal = getattr(pronunciation_player, "status_changed", None)
        if signal is not None:
            signal.connect(self._update_pronunciation_status)

    def _update_pronunciation_status(self, status: object) -> None:
        if self.pronunciation_player is None:
            self.pronunciation_status_label.setText("随系统声音播放（未初始化）")
            return
        if bool(getattr(status, "available", False)):
            voice_name = str(getattr(status, "voice_name", "") or "英语声音")
            self.pronunciation_status_label.setText(f"已启用 · {voice_name}")
        else:
            self.pronunciation_status_label.setText("未检测到英语声音，可下载语音包")
