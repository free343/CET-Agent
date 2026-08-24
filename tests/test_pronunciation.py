from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QApplication

from app.db.models import WordLevel
from app.infrastructure.pronunciation import PronunciationPlayer
from app.services.lexical_fact_view import LinkedWordReference
from app.services.review_item_view import ReviewItem
from app.services.word_detail_service import WordDetailView
from app.ui.acquisition_page import AcquisitionPage
from app.ui.main_window import MainWindow
from app.ui.widgets.pronunciation_widgets import PronunciationPlayButton
from app.ui.word_detail_controller import WordDetailController
from app.utils.datetime_utils import UTC


class FakeSpeech:
    def __init__(self, _engine: str, _parent) -> None:
        self.locale = QLocale("zh_CN")
        self.voice = None
        self.spoken: list[str] = []
        self.stops = 0

    def setLocale(self, locale: QLocale) -> None:
        self.locale = locale

    def availableVoices(self):
        if self.locale.language() == QLocale.Language.English:
            return [_FakeVoice("Test English", self.locale)]
        return [_FakeVoice("Test Chinese", QLocale("zh_CN"))]

    def setVoice(self, voice) -> None:
        self.voice = voice

    def say(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        self.stops += 1

    def deleteLater(self) -> None:
        return None


def test_player_requires_real_english_voice_and_limits_playback() -> None:
    app = QApplication.instance() or QApplication([])
    speeches: list[FakeSpeech] = []

    def factory(engine: str, parent) -> FakeSpeech:
        speech = FakeSpeech(engine, parent)
        speeches.append(speech)
        return speech

    player = PronunciationPlayer(
        engine_factory=factory,
        engine_provider=lambda: ["mock", "fake"],
        platform_name="win32",
    )
    assert player.available
    assert player.status.voice_name == "Test English"
    assert player.play("  main   ")
    assert speeches[-1].spoken == ["main"]
    player.stop()
    assert speeches[-1].stops >= 2
    player.deleteLater()
    app.processEvents()


def test_missing_english_voice_opens_official_settings_only() -> None:
    app = QApplication.instance() or QApplication([])
    opened: list[str] = []
    player = PronunciationPlayer(
        engine_factory=lambda engine, parent: FakeSpeech(engine, parent),
        engine_provider=lambda: ["mock", "fake"],
        url_opener=lambda url: opened.append(url.toString()) or True,
        platform_name="win32",
    )
    # Replace the fake's English discovery with a Chinese-only engine.
    player._engine_factory = lambda engine, parent: _ChineseOnlySpeech(engine, parent)
    player.refresh()
    assert not player.available
    assert player.open_voice_settings()
    assert opened == ["ms-settings:regionlanguage"]
    player.deleteLater()
    app.processEvents()


class _ChineseOnlySpeech(FakeSpeech):
    def availableVoices(self):
        return [_FakeVoice("Test Chinese", QLocale("zh_CN"))]


class _FakeVoice:
    def __init__(self, name: str, locale: QLocale) -> None:
        self._name = name
        self._locale = locale

    def name(self) -> str:
        return self._name

    def locale(self) -> QLocale:
        return self._locale


def test_play_button_isolated_to_the_current_word() -> None:
    app = QApplication.instance() or QApplication([])

    class FakePlayer:
        class Status:
            available = True
            message = ""

        status = Status()

        def __init__(self) -> None:
            self.words: list[str] = []

        def play(self, word: str) -> bool:
            self.words.append(word)
            return True

    player = FakePlayer()
    button = PronunciationPlayButton(player)
    button.set_word("hidden", enabled=False)
    assert not button.isEnabled()
    button.set_word("adapt")
    assert button.isEnabled()
    button.click()
    assert player.words == ["adapt"]
    button.set_word("major")
    button.click()
    assert player.words == ["adapt", "major"]
    button.deleteLater()
    app.processEvents()


def test_detail_controller_autoplays_only_the_accepted_generation() -> None:
    app = QApplication.instance() or QApplication([])

    class FakePlayer:
        class Status:
            available = True
            message = ""

        status = Status()

        def __init__(self) -> None:
            self.words: list[str] = []
            self.stops = 0

        def play(self, word: str) -> bool:
            self.words.append(word)
            return True

        def stop(self) -> None:
            self.stops += 1

    player = FakePlayer()
    controller = WordDetailController(object(), pronunciation_player=player)  # type: ignore[arg-type]
    controller._generation = 2
    controller.dialog.show()
    view = WordDetailView(
        reference=LinkedWordReference(word="major", meaning="主要的"),
        word="major",
        phonetic="/ˈmeɪdʒər/",
        meaning="主要的",
        level="CET4",
        example="",
        example_translation="",
        sections=(),
    )
    controller._loaded(1, view)
    assert player.words == []
    controller._loaded(2, view)
    # Autoplay must wait until Qt has returned to the GUI event loop and the
    # freshly populated dialog can actually be presented.
    assert player.words == []
    app.processEvents()
    assert player.words == ["major"]
    controller.close()
    controller.dialog.deleteLater()
    app.processEvents()


def test_window_activation_does_not_rescan_voice_without_settings_request() -> None:
    calls: list[bool] = []
    window = SimpleNamespace(
        _shutdown_started=False,
        _pronunciation_refresh_pending=False,
        _schedule_pronunciation_refresh=lambda: calls.append(True),
    )

    MainWindow._application_state_changed(
        window,
        Qt.ApplicationState.ApplicationActive,
    )

    assert calls == []
    window._pronunciation_refresh_pending = True
    MainWindow._application_state_changed(
        window,
        Qt.ApplicationState.ApplicationActive,
    )
    assert calls == [True]


def test_acquisition_answer_hidden_stages_disable_pronunciation() -> None:
    app = QApplication.instance() or QApplication([])

    class FakePlayer:
        class Status:
            available = True
            message = ""

        status = Status()

        def play(self, _word: str) -> bool:
            return True

        def stop(self) -> None:
            return None

    class Service:
        group_size = 10
        extra_study_limit = 5

    page = AcquisitionPage(Service(), pronunciation_player=FakePlayer())  # type: ignore[arg-type]
    page.queue = [
        ReviewItem(
            word_id=1,
            word="adapt",
            phonetic="/əˈdæpt/",
            meaning="适应",
            example="Students adapt.",
            level=WordLevel.CET4,
            lapse_count=0,
            error_count=0,
            next_review_at=datetime.now(UTC),
            proficiency_level=1,
        )
    ]
    page._show_next()
    assert not page.card.pronunciation_button.isEnabled()
    assert page.card.pronunciation_button._word == ""
    page.deleteLater()
    app.processEvents()
