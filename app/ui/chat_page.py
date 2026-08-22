"""Scoped CET vocabulary assistant with basic model-routing UI."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Protocol

from PySide6.QtWidgets import (
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
    ) -> AIAnswer: ...


class ChatPage(QWidget):
    def __init__(self, service: ChatService) -> None:
        super().__init__()
        self.service = service
        self.pending_question = ""
        self.history: deque[ChatExchange] = deque(maxlen=MAX_CHAT_HISTORY_EXCHANGES)
        self.worker: AsyncWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        title = QLabel("AI 词汇助手")
        title.setObjectName("PageTitle")
        subtitle = QLabel("可询问四六级词汇、基础语法、词义辨析和记忆技巧。")
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.document().setMaximumBlockCount(CHAT_TRANSCRIPT_MAX_BLOCKS)
        self.transcript.setPlaceholderText("例如：economic 和 economical 有什么区别？")
        layout.addWidget(self.transcript, 1)

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
        self.pending_question = question
        self.input.clear()
        self.transcript.append(f"你：{question}\n")
        assessment = self.service.route_question(question)
        if assessment.route is QueryRoute.CONFIRM_ADVANCED:
            self.routing_reason.setText(f"{assessment.reason} 是否使用高级模型回答？")
            self._set_input_enabled(False)
            self.routing_frame.show()
        else:
            self._start_request(False)

    def _start_request(self, use_advanced: bool) -> None:
        if not self.pending_question or self.worker is not None:
            return
        self.routing_frame.hide()
        self._set_input_enabled(False)
        self.transcript.append("CET-Agent：正在思考…")
        question = self.pending_question
        history = tuple(self.history)
        self.worker = AsyncWorker(
            lambda: self.service.ask(
                question,
                use_advanced=use_advanced,
                history=history,
            ),
            parent=self,
        )
        self.worker.result_ready.connect(self._show_answer)
        self.worker.failed.connect(self._show_failure)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _show_answer(self, answer: AIAnswer) -> None:
        suffix = "（降级响应）" if answer.degraded else ""
        self.transcript.append(
            f"CET-Agent：{answer.text}\n"
            f"置信度 {answer.confidence:.0%} · {answer.model}{suffix}\n"
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

    def _show_failure(self, message: str) -> None:
        self.transcript.append(f"CET-Agent：请求失败：{message}\n")

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.pending_question = ""
        self._set_input_enabled(True)

    def _set_input_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
