from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ai.conversation import ChatExchange
from app.ai.schemas import AIAnswer
from app.domain.query_routing import QueryAssessment, QueryRoute, QueryRoutingPolicy
from app.ui.chat_page import (
    CHAT_TRANSCRIPT_MAX_BLOCKS,
    ChatContext,
    ChatPage,
    ChatPanel,
)


class LowConfidenceService:
    advanced_available = False

    @staticmethod
    def route_question(_question: str) -> QueryAssessment:
        return QueryAssessment(
            QueryRoute.CONFIRM_ADVANCED,
            0.4,
            "问题较长。",
        )


class RecordingChatService:
    advanced_available = False

    def __init__(self) -> None:
        self.histories: list[tuple[ChatExchange, ...]] = []
        self.contexts: list[str | None] = []

    @staticmethod
    def route_question(_question: str) -> QueryAssessment:
        return QueryAssessment(QueryRoute.LOCAL, 0.9, "本地回答。")

    def ask(
        self,
        question: str,
        *,
        use_advanced: bool = False,
        history=(),
        context: str | None = None,
    ) -> AIAnswer:
        self.histories.append(tuple(history))
        self.contexts.append(context)
        return AIAnswer(text=f"answer to {question}", confidence=0.9, model="fake")


def _wait_until_idle(page: ChatPanel, app: QApplication) -> None:
    while page.worker is not None:
        worker = page.worker
        assert worker.wait(2_000)
        app.processEvents()


def test_pending_routing_question_cannot_be_overwritten() -> None:
    app = QApplication.instance() or QApplication([])
    page = ChatPage(LowConfidenceService())
    page.input.setText("first complex question")
    page.send()

    assert page.pending_question == "first complex question"
    assert page.input.isEnabled() is False
    assert page.send_button.isEnabled() is False
    assert "问题较长" in page.routing_reason.text()

    page.input.setText("second complex question")
    page.send()
    app.processEvents()

    assert page.pending_question == "first complex question"
    assert "second complex question" not in page.transcript.toPlainText()
    page.deleteLater()


def test_chat_widgets_enforce_input_and_transcript_budgets() -> None:
    app = QApplication.instance() or QApplication([])
    page = ChatPage(LowConfidenceService())

    page.input.setText("x" * (QueryRoutingPolicy().max_question_characters + 10))
    for index in range(CHAT_TRANSCRIPT_MAX_BLOCKS + 20):
        page.transcript.append(f"line-{index}")
    app.processEvents()

    assert len(page.input.text()) == QueryRoutingPolicy().max_question_characters
    assert page.transcript.document().blockCount() <= CHAT_TRANSCRIPT_MAX_BLOCKS
    assert "line-0" not in page.transcript.toPlainText()
    page.deleteLater()


def test_second_question_receives_first_exchange_as_context() -> None:
    app = QApplication.instance() or QApplication([])
    service = RecordingChatService()
    page = ChatPage(service)

    page.input.setText("adapt meaning")
    page.send()
    _wait_until_idle(page, app)
    page.input.setText("give another example")
    page.send()
    _wait_until_idle(page, app)

    assert service.histories[0] == ()
    assert service.histories[1] == (
        ChatExchange(user="adapt meaning", assistant="answer to adapt meaning"),
    )
    page.deleteLater()


def test_compact_chat_panel_captures_current_word_context() -> None:
    app = QApplication.instance() or QApplication([])
    service = RecordingChatService()
    panel = ChatPanel(
        service,
        compact=True,
        context_provider=lambda: ChatContext(
            "adapt",
            "word=adapt; meaning=适应；改编",
        ),
    )

    panel.input.setText("怎么记？")
    panel.send()
    _wait_until_idle(panel, app)

    assert service.contexts == ["word=adapt; meaning=适应；改编"]
    assert "关于 adapt" in panel.transcript.toPlainText()
    panel.deleteLater()
