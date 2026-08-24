"""Scoped CET vocabulary assistant with basic model-routing UI."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from html import escape
from typing import Protocol

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ai.conversation import MAX_CHAT_HISTORY_EXCHANGES, ChatExchange
from app.ai.schemas import AIAnswer
from app.domain.query_routing import QueryAssessment, QueryRoute, QueryRoutingPolicy
from app.ui.widgets.async_worker import AsyncWorker

CHAT_TRANSCRIPT_MAX_BLOCKS = 200
CHAT_USER_BACKGROUND = "#e0e7ff"
CHAT_USER_FOREGROUND = "#312e81"
CHAT_ASSISTANT_BACKGROUND = "#f1f5f9"
CHAT_ASSISTANT_FOREGROUND = "#0f172a"
CHAT_STATUS_BACKGROUND = "#fef3c7"
CHAT_STATUS_FOREGROUND = "#92400e"
CHAT_ERROR_BACKGROUND = "#fee2e2"
CHAT_ERROR_FOREGROUND = "#991b1b"
MODEL_MODE_AUTO = "auto"
MODEL_MODE_LOCAL = "local"
MODEL_MODE_ADVANCED = "advanced"
STUDY_ASSISTANT_MIN_WIDTH = 340
STUDY_WORKSPACE_INITIAL_SIZES = (660, 400)


@dataclass(frozen=True, slots=True)
class ChatContext:
    label: str
    content: str


@dataclass(frozen=True, slots=True)
class AdvancedRetrySnapshot:
    question: str
    context: ChatContext | None
    history: tuple[ChatExchange, ...]
    context_generation: int


class ChatService(Protocol):
    @property
    def advanced_available(self) -> bool: ...

    def route_question(self, question: str) -> QueryAssessment: ...

    def ask(
        self,
        question: str,
        *,
        use_advanced: bool = False,
        history: Sequence[ChatExchange] = (),
        context: str | None = None,
    ) -> AIAnswer: ...


class ChatPanel(QWidget):
    def __init__(
        self,
        service: ChatService,
        *,
        compact: bool = False,
        context_provider: Callable[[], ChatContext | None] | None = None,
        on_question_submitted: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.compact = compact
        self.context_provider = context_provider
        self.on_question_submitted = on_question_submitted
        self.pending_question = ""
        self.pending_context: ChatContext | None = None
        self.history: deque[ChatExchange] = deque(maxlen=MAX_CHAT_HISTORY_EXCHANGES)
        self._history_context_label: str | None = None
        self._context_generation = 0
        self._pending_context_generation: int | None = None
        self._pending_use_advanced = False
        self._pending_history: tuple[ChatExchange, ...] = ()
        self._advanced_retry_snapshot: AdvancedRetrySnapshot | None = None
        self.worker: AsyncWorker | None = None
        layout = QVBoxLayout(self)
        margin = 16 if compact else 32
        layout.setContentsMargins(margin, 20 if compact else 28, margin, 20)
        layout.setSpacing(14)
        title = QLabel("随学随问" if compact else "AI 词汇助手")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "自动关联发送时的当前单词。"
            if compact
            else "可询问四六级词汇、基础语法、词义辨析和记忆技巧。"
        )
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        if compact:
            quick_row = QHBoxLayout()
            for label, question in (
                ("怎么记", "这个词怎么记？"),
                ("讲例句", "请解释这个词在例句中的用法。"),
                (
                    "辨析",
                    "请根据当前词卡辨析这个词的核心用法、常见搭配和容易误用的边界。",
                ),
            ):
                button = QPushButton(label)
                button.clicked.connect(
                    lambda _checked=False, value=question: self._send_quick(value)
                )
                quick_row.addWidget(button)
            layout.addLayout(quick_row)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.document().setMaximumBlockCount(CHAT_TRANSCRIPT_MAX_BLOCKS)
        self.transcript.setPlaceholderText("例如：economic 和 economical 有什么区别？")
        layout.addWidget(self.transcript, 1)

        upgrade_row = QHBoxLayout()
        upgrade_row.addStretch()
        self.upgrade_button = QPushButton("对内容不满意？试试高级模型")
        self.upgrade_button.setObjectName("AdvancedRetryButton")
        self.upgrade_button.setToolTip("使用相同问题和词卡上下文重新回答")
        self.upgrade_button.clicked.connect(self._retry_with_advanced)
        upgrade_row.addWidget(self.upgrade_button)
        layout.addLayout(upgrade_row)
        self.upgrade_button.hide()

        model_row = QHBoxLayout()
        model_label = QLabel("回答模型")
        self.model_selector = QComboBox()
        self.model_selector.setObjectName("ChatModelSelector")
        local_name = str(getattr(service, "local_model_name", "本地模型"))
        advanced_name = getattr(service, "advanced_model_name", None)
        self.model_selector.addItem("自动选择（推荐）", MODEL_MODE_AUTO)
        self.model_selector.addItem(f"本地 · {local_name}", MODEL_MODE_LOCAL)
        if service.advanced_available:
            suffix = str(advanced_name or "已配置")
            self.model_selector.addItem(
                f"高级 · {suffix}",
                MODEL_MODE_ADVANCED,
            )
        else:
            self.model_selector.addItem(
                "高级模型（未配置，请到设置页）",
                MODEL_MODE_ADVANCED,
            )
            selector_model = self.model_selector.model()
            if isinstance(selector_model, QStandardItemModel):
                advanced_item = selector_model.item(self.model_selector.count() - 1)
                if advanced_item is not None:
                    advanced_item.setEnabled(False)
        model_row.addWidget(model_label)
        model_row.addWidget(self.model_selector, 1)
        layout.addLayout(model_row)
        self.model_hint = QLabel()
        self.model_hint.setObjectName("ChatModelHint")
        self.model_hint.setWordWrap(True)
        self.model_hint.setStyleSheet("color: #64748b;")
        layout.addWidget(self.model_hint)
        self.model_selector.currentIndexChanged.connect(self._model_mode_changed)
        self._model_mode_changed()

        self.routing_frame = QFrame()
        self.routing_frame.setObjectName("Card")
        routing_layout = QHBoxLayout(self.routing_frame)
        self.routing_reason = QLabel("这个问题比较复杂，是否使用高级模型回答？")
        routing_layout.addWidget(self.routing_reason)
        routing_layout.addStretch()
        self.advanced_button = QPushButton("使用高级模型")
        self.advanced_button.setObjectName("PrimaryButton")
        self.advanced_button.setEnabled(service.advanced_available)
        if not service.advanced_available:
            self.advanced_button.setToolTip("尚未配置高级模型 Provider")
        self.local_button = QPushButton("继续使用本地模型")
        self.advanced_button.clicked.connect(lambda: self._start_request(True))
        self.local_button.clicked.connect(lambda: self._start_request(False))
        routing_layout.addWidget(self.advanced_button)
        routing_layout.addWidget(self.local_button)
        layout.addWidget(self.routing_frame)
        self.routing_frame.hide()

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setMaxLength(QueryRoutingPolicy().max_question_characters)
        self.input.setPlaceholderText("输入英语学习问题…")
        self.input.returnPressed.connect(self.send)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.clicked.connect(self.send)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

    def send(self) -> None:
        question = self.input.text().strip()
        if not question or self.worker is not None or self.pending_question:
            return
        context: ChatContext | None = None
        if self.context_provider is not None:
            context = self.context_provider()
            self._apply_context(context)
        self._clear_advanced_retry()
        self.input.clear()
        if self.compact and self.context_provider is not None and context is None:
            self._append_message("你", question, message_type="user")
            self._append_message(
                "CET-Agent",
                "当前没有可用的词卡上下文。请先完成当前小题，"
                "或切换到正在显示答案的词卡后再问。",
                message_type="status",
            )
            return
        self.pending_question = question
        self.pending_context = context
        self._pending_context_generation = self._context_generation
        if self.on_question_submitted is not None:
            self.on_question_submitted()
        context_label = (
            f"（关于 {self.pending_context.label}）"
            if self.pending_context is not None
            else ""
        )
        self._append_message(
            f"你{context_label}",
            question,
            message_type="user",
        )
        assessment = self.service.route_question(question)
        selected_mode = self.model_selector.currentData()
        if selected_mode == MODEL_MODE_ADVANCED:
            self._start_request(True)
        elif selected_mode == MODEL_MODE_LOCAL:
            self._start_request(False)
        elif assessment.route is QueryRoute.CONFIRM_ADVANCED:
            self.routing_reason.setText(f"{assessment.reason} 是否使用高级模型回答？")
            self._set_input_enabled(False)
            self.routing_frame.show()
        else:
            self._start_request(False)

    def _start_request(
        self,
        use_advanced: bool,
        *,
        history_override: tuple[ChatExchange, ...] | None = None,
    ) -> None:
        if not self.pending_question or self.worker is not None:
            return
        self.routing_frame.hide()
        self._set_input_enabled(False)
        self._pending_use_advanced = use_advanced
        self._append_message(
            "CET-Agent",
            "正在调用高级模型…" if use_advanced else "正在思考…",
            message_type="status",
        )
        question = self.pending_question
        history = (
            history_override if history_override is not None else tuple(self.history)
        )
        self._pending_history = history
        request = partial(
            self.service.ask,
            question,
            use_advanced=use_advanced,
            history=history,
        )
        if self.pending_context:
            request = partial(request, context=self.pending_context.content)
        self.worker = AsyncWorker(
            request,
            parent=self,
        )
        self.worker.result_ready.connect(self._show_answer)
        self.worker.failed.connect(self._show_failure)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _show_answer(self, answer: AIAnswer) -> None:
        if not self._pending_request_is_current():
            return
        suffix = "（降级响应）" if answer.degraded else ""
        if answer.model in {
            "deterministic-memory",
            "deterministic-lexical-fact",
            "scope-policy",
        }:
            metadata = "本地规则 · 无模型调用"
        elif self._pending_use_advanced:
            metadata = f"高级模型 · {answer.model}{suffix}"
        else:
            metadata = f"本地模型 · {answer.model}{suffix}"
        self._append_message(
            "CET-Agent",
            f"{answer.text}\n{metadata}",
            message_type="assistant" if not answer.degraded else "error",
        )
        if (
            self.pending_question
            and not answer.degraded
            and answer.model != "scope-policy"
        ):
            self.history.append(
                ChatExchange(
                    user=self.pending_question,
                    assistant=answer.text,
                )
            )
        if (
            self.pending_question
            and not self._pending_use_advanced
            and not answer.degraded
            and answer.model
            not in {
                "deterministic-memory",
                "deterministic-lexical-fact",
                "scope-policy",
            }
            and self.service.advanced_available
            and self._pending_context_generation is not None
        ):
            self._advanced_retry_snapshot = AdvancedRetrySnapshot(
                question=self.pending_question,
                context=self.pending_context,
                history=self._pending_history,
                context_generation=self._pending_context_generation,
            )
            self.upgrade_button.show()

    def _show_failure(self, message: str) -> None:
        if not self._pending_request_is_current():
            return
        self._append_message(
            "CET-Agent",
            f"请求失败：{message}",
            message_type="error",
        )

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.pending_question = ""
        self.pending_context = None
        self._pending_context_generation = None
        self._pending_use_advanced = False
        self._pending_history = ()
        self._set_input_enabled(True)

    def _retry_with_advanced(self) -> None:
        snapshot = self._advanced_retry_snapshot
        if (
            snapshot is None
            or not self.service.advanced_available
            or self.worker is not None
            or self.pending_question
            or snapshot.context_generation != self._context_generation
            or (
                self.context_provider is not None
                and self._context_label(self.context_provider())
                != self._history_context_label
            )
        ):
            self._clear_advanced_retry()
            return
        self._clear_advanced_retry()
        self.history.clear()
        self.history.extend(snapshot.history)
        self.pending_question = snapshot.question
        self.pending_context = snapshot.context
        self._pending_context_generation = snapshot.context_generation
        self._start_request(True, history_override=snapshot.history)

    def _clear_advanced_retry(self) -> None:
        self._advanced_retry_snapshot = None
        self.upgrade_button.hide()

    def _set_input_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.model_selector.setEnabled(enabled)

    def _model_mode_changed(self, _index: int = -1) -> None:
        selected_mode = self.model_selector.currentData()
        if selected_mode == MODEL_MODE_ADVANCED:
            hint = "每次提问直接调用高级模型，可能产生网络流量和 API 费用。"
        elif selected_mode == MODEL_MODE_LOCAL:
            hint = "始终使用本地模型；“怎么记”仍优先使用零调用的本地规则。"
        elif self.service.advanced_available:
            hint = "普通问题使用本地模型；复杂或词汇扩展问题会先询问是否升级。"
        else:
            hint = "当前仅可使用本地模型；可在“设置”查看高级模型配置方法。"
        self.model_hint.setText(hint)

    def _send_quick(self, question: str) -> None:
        if self.worker is not None or self.pending_question:
            return
        self.input.setText(question)
        self.send()

    def context_changed(self) -> None:
        """Reset compact conversation state for an explicitly new card."""
        if self.context_provider is None:
            return
        self._apply_context(self.context_provider(), force=True)

    def _apply_context(
        self,
        context: ChatContext | None,
        *,
        force: bool = False,
    ) -> None:
        context_label = self._context_label(context)
        if not force and context_label == self._history_context_label:
            return
        self._context_generation += 1
        self._history_context_label = context_label
        self.history.clear()
        self.transcript.clear()
        self.routing_frame.hide()
        self._clear_advanced_retry()
        if self.worker is None:
            self.pending_question = ""
            self.pending_context = None
            self._pending_context_generation = None
            self._pending_use_advanced = False
            self._pending_history = ()
            self._set_input_enabled(True)

    def _pending_request_is_current(self) -> bool:
        if self._pending_context_generation != self._context_generation:
            return False
        if self.context_provider is None:
            return True
        return (
            self._context_label(self.context_provider()) == self._history_context_label
        )

    @staticmethod
    def _context_label(context: ChatContext | None) -> str | None:
        if context is None:
            return None
        label = context.label.strip().casefold()
        return label or None

    def _append_message(
        self,
        speaker: str,
        text: str,
        *,
        message_type: str,
    ) -> None:
        colors = {
            "user": (CHAT_USER_BACKGROUND, CHAT_USER_FOREGROUND),
            "assistant": (CHAT_ASSISTANT_BACKGROUND, CHAT_ASSISTANT_FOREGROUND),
            "status": (CHAT_STATUS_BACKGROUND, CHAT_STATUS_FOREGROUND),
            "error": (CHAT_ERROR_BACKGROUND, CHAT_ERROR_FOREGROUND),
        }
        background, foreground = colors[message_type]
        safe_speaker = escape(speaker)
        safe_text = escape(text).replace("\n", "<br>")
        self.transcript.append(
            f'<span style="background-color:{background}; color:{foreground};">'
            f"<b>{safe_speaker}</b><br>{safe_text}</span>"
        )


class ChatPage(ChatPanel):
    def __init__(self, service: ChatService) -> None:
        super().__init__(service)
