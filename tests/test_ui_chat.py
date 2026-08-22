from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.chat_page import ChatPage


class LowConfidenceService:
    advanced_available = False

    @staticmethod
    def assess_question(_question: str) -> float:
        return 0.1


def test_pending_routing_question_cannot_be_overwritten() -> None:
    app = QApplication.instance() or QApplication([])
    page = ChatPage(LowConfidenceService())
    page.input.setText("first complex question")
    page.send()

    assert page.pending_question == "first complex question"
    assert page.input.isEnabled() is False
    assert page.send_button.isEnabled() is False

    page.input.setText("second complex question")
    page.send()
    app.processEvents()

    assert page.pending_question == "first complex question"
    assert "second complex question" not in page.transcript.toPlainText()
    page.deleteLater()
