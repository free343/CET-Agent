from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ai.conversation import ChatExchange
from app.ai.schemas import AIAnswer
from app.domain.query_routing import QueryAssessment, QueryRoute, QueryRoutingPolicy
from app.ui.chat_page import (
    CHAT_TRANSCRIPT_MAX_BLOCKS,
    MODEL_MODE_ADVANCED,
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
    local_model_name = "fake-local"
    advanced_model_name = None

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.histories: list[tuple[ChatExchange, ...]] = []
        self.contexts: list[str | None] = []
        self.advanced_choices: list[bool] = []

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
        self.questions.append(question)
        self.histories.append(tuple(history))
        self.contexts.append(context)
        self.advanced_choices.append(use_advanced)
        return AIAnswer(text=f"answer to {question}", confidence=0.9, model="fake")


class BlockingChatService(RecordingChatService):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def ask(
        self,
        question: str,
        *,
        use_advanced: bool = False,
        history=(),
        context: str | None = None,
    ) -> AIAnswer:
        self.questions.append(question)
        self.histories.append(tuple(history))
        self.contexts.append(context)
        self.advanced_choices.append(use_advanced)
        self.started.set()
        assert self.release.wait(2)
        return AIAnswer(text="late answer for adapt", confidence=0.9, model="fake")


class UnsafeAnswerService(RecordingChatService):
    def ask(
        self,
        question: str,
        *,
        use_advanced: bool = False,
        history=(),
        context: str | None = None,
    ) -> AIAnswer:
        self.questions.append(question)
        self.advanced_choices.append(use_advanced)
        return AIAnswer(text="<unsafe>& answer", confidence=0.9, model="fake")


class AdvancedRecordingChatService(RecordingChatService):
    advanced_available = True
    advanced_model_name = "deepseek-v4-flash"

    @staticmethod
    def route_question(_question: str) -> QueryAssessment:
        return QueryAssessment(
            QueryRoute.CONFIRM_ADVANCED,
            0.48,
            "词汇扩展需要高级模型。",
        )


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


def test_unconfigured_advanced_option_is_visible_but_disabled() -> None:
    app = QApplication.instance() or QApplication([])
    page = ChatPage(RecordingChatService())
    advanced_index = page.model_selector.findData(MODEL_MODE_ADVANCED)

    assert advanced_index >= 0
    assert "未配置" in page.model_selector.itemText(advanced_index)
    model_index = page.model_selector.model().index(advanced_index, 0)
    assert not (
        page.model_selector.model().flags(model_index) & Qt.ItemFlag.ItemIsEnabled
    )
    page.deleteLater()
    app.processEvents()


def test_explicit_advanced_model_selection_bypasses_confirmation() -> None:
    app = QApplication.instance() or QApplication([])
    service = AdvancedRecordingChatService()
    page = ChatPage(service)
    advanced_index = page.model_selector.findData(MODEL_MODE_ADVANCED)
    assert advanced_index >= 0
    page.model_selector.setCurrentIndex(advanced_index)

    page.input.setText("main 有什么近义词？")
    page.send()
    _wait_until_idle(page, app)

    assert service.advanced_choices == [True]
    assert page.routing_frame.isHidden()
    assert "高级模型" in page.transcript.toPlainText()
    page.deleteLater()


def test_local_answer_offers_one_click_advanced_retry_without_confidence() -> None:
    app = QApplication.instance() or QApplication([])
    service = AdvancedRecordingChatService()
    page = ChatPage(service)
    local_index = page.model_selector.findData("local")
    page.model_selector.setCurrentIndex(local_index)

    page.input.setText("adapt 是什么意思？")
    page.send()
    _wait_until_idle(page, app)

    transcript = page.transcript.toPlainText()
    assert "置信度" not in transcript
    assert "本地模型 · fake" in transcript
    assert page.upgrade_button.isHidden() is False

    page.upgrade_button.click()
    _wait_until_idle(page, app)

    assert service.questions == ["adapt 是什么意思？", "adapt 是什么意思？"]
    assert service.advanced_choices == [False, True]
    assert service.histories == [(), ()]
    assert len(page.history) == 1
    assert page.history[0].user == "adapt 是什么意思？"
    assert page.upgrade_button.isHidden() is True
    transcript = page.transcript.toPlainText()
    assert "高级模型 · fake" in transcript
    assert "置信度" not in transcript
    page.deleteLater()


def test_card_change_invalidates_local_answer_upgrade_offer() -> None:
    app = QApplication.instance() or QApplication([])
    service = AdvancedRecordingChatService()
    current_context = [ChatContext("adapt", "word=adapt\nmeaning=适应")]
    panel = ChatPanel(
        service,
        compact=True,
        context_provider=lambda: current_context[0],
    )
    local_index = panel.model_selector.findData("local")
    panel.model_selector.setCurrentIndex(local_index)

    panel.input.setText("解释这个词。")
    panel.send()
    _wait_until_idle(panel, app)
    assert panel.upgrade_button.isHidden() is False

    current_context[0] = ChatContext("adopt", "word=adopt\nmeaning=采用")
    panel.context_changed()
    panel.upgrade_button.click()
    app.processEvents()

    assert panel.upgrade_button.isHidden() is True
    assert service.questions == ["解释这个词。"]
    panel.deleteLater()


def test_deterministic_local_rule_does_not_offer_model_retry() -> None:
    class DeterministicService(AdvancedRecordingChatService):
        def ask(
            self,
            question: str,
            *,
            use_advanced: bool = False,
            history=(),
            context: str | None = None,
        ) -> AIAnswer:
            self.questions.append(question)
            self.histories.append(tuple(history))
            self.contexts.append(context)
            self.advanced_choices.append(use_advanced)
            return AIAnswer(
                text="本地规则助记",
                confidence=1.0,
                model="deterministic-memory",
            )

    app = QApplication.instance() or QApplication([])
    page = ChatPage(DeterministicService())
    page.input.setText("adapt 怎么记？")
    page.send()
    _wait_until_idle(page, app)

    assert page.upgrade_button.isHidden() is True
    assert "置信度" not in page.transcript.toPlainText()
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


def test_compact_chat_panel_does_not_carry_history_across_words() -> None:
    app = QApplication.instance() or QApplication([])
    service = RecordingChatService()
    current_context = [
        ChatContext(
            "adapt",
            "word=adapt; meaning=适应；改编",
        )
    ]
    panel = ChatPanel(
        service,
        compact=True,
        context_provider=lambda: current_context[0],
    )

    panel.input.setText("这个词怎么记？")
    panel.send()
    _wait_until_idle(panel, app)
    current_context[0] = ChatContext(
        "adopt",
        "word=adopt; meaning=采用；收养",
    )
    panel.context_changed()

    assert panel.transcript.toPlainText() == ""
    assert tuple(panel.history) == ()

    panel.input.setText("这个词怎么记？")
    panel.send()
    _wait_until_idle(panel, app)
    panel.input.setText("再给一个例句。")
    panel.send()
    _wait_until_idle(panel, app)

    assert service.contexts == [
        "word=adapt; meaning=适应；改编",
        "word=adopt; meaning=采用；收养",
        "word=adopt; meaning=采用；收养",
    ]
    assert service.histories[0] == ()
    assert service.histories[1] == ()
    assert service.histories[2] == (
        ChatExchange(user="这个词怎么记？", assistant="answer to 这个词怎么记？"),
    )
    panel.deleteLater()


def test_compact_context_change_discards_late_previous_word_answer() -> None:
    app = QApplication.instance() or QApplication([])
    service = BlockingChatService()
    current_context = [ChatContext("adapt", "word=adapt\nmeaning=适应")]
    panel = ChatPanel(
        service,
        compact=True,
        context_provider=lambda: current_context[0],
    )
    panel.context_changed()
    panel.input.setText("解释这个词。")
    panel.send()
    assert service.started.wait(2)

    current_context[0] = ChatContext("adopt", "word=adopt\nmeaning=采用")
    panel.context_changed()
    service.release.set()
    _wait_until_idle(panel, app)

    assert panel.transcript.toPlainText() == ""
    assert tuple(panel.history) == ()
    panel.deleteLater()


def test_compact_panel_without_context_refuses_without_provider_call() -> None:
    app = QApplication.instance() or QApplication([])
    service = RecordingChatService()
    panel = ChatPanel(
        service,
        compact=True,
        context_provider=lambda: None,
    )

    panel.input.setText("这个词怎么记？")
    panel.send()
    app.processEvents()

    assert panel.worker is None
    assert service.questions == []
    assert "当前没有可用的词卡上下文" in panel.transcript.toPlainText()
    panel.deleteLater()


def test_chat_roles_use_distinct_colors_and_escape_untrusted_text() -> None:
    app = QApplication.instance() or QApplication([])
    panel = ChatPage(UnsafeAnswerService())

    panel.input.setText("adapt <b>meaning</b>")
    panel.send()
    _wait_until_idle(panel, app)

    transcript_html = panel.transcript.toHtml().casefold()
    transcript_text = panel.transcript.toPlainText()
    assert "#e0e7ff" in transcript_html
    assert "#f1f5f9" in transcript_html
    assert "<unsafe>" not in transcript_html
    assert "<unsafe>& answer" in transcript_text
    assert "你" in transcript_text
    assert "CET-Agent" in transcript_text
    panel.deleteLater()


def test_compact_distinction_action_sends_a_routable_grounded_question() -> None:
    app = QApplication.instance() or QApplication([])
    service = RecordingChatService()
    panel = ChatPanel(
        service,
        compact=True,
        context_provider=lambda: ChatContext(
            "adapt",
            "word=adapt\nmeaning=适应；改编\ncollocations=adapt to｜适应",
        ),
    )

    distinction_button = next(
        button
        for button in panel.findChildren(type(panel.send_button))
        if button.text() == "辨析"
    )
    distinction_button.click()
    _wait_until_idle(panel, app)

    assert service.questions == [
        "请根据当前词卡辨析这个词的核心用法、常见搭配和容易误用的边界。"
    ]
    assert QueryRoutingPolicy().assess(service.questions[0]).route is QueryRoute.LOCAL
    assert service.contexts == [
        "word=adapt\nmeaning=适应；改编\ncollocations=adapt to｜适应"
    ]
    panel.deleteLater()
