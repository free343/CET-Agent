from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.domain.query_routing import QueryAssessment, QueryRoute
from app.ui.chat_page import ChatPage


class LowConfidenceService:
    advanced_available = False

    @staticmethod
    def route_question(_question: str) -> QueryAssessment:
        return QueryAssessment(
            QueryRoute.CONFIRM_ADVANCED,
            0.4,
            "问题较长。",
        )


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
