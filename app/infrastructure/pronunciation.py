"""Local, non-blocking pronunciation through the operating system TTS stack."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtCore import QLocale, QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtTextToSpeech import QTextToSpeech, QVoice


@dataclass(frozen=True, slots=True)
class PronunciationStatus:
    """The safe-to-render state of the local English voice setup."""

    available: bool
    engine: str = ""
    voice_name: str = ""
    locale_name: str = ""
    message: str = ""


def _is_english_voice(voice: QVoice) -> bool:
    return voice.locale().language() == QLocale.Language.English


class PronunciationPlayer(QObject):
    """Own one selected system voice and expose a tiny UI-safe playback API.

    Voice discovery is intentionally explicit: a locale is selected before voices
    are enumerated, and only an English voice from a real OS engine is accepted.
    The mock Qt engine and any Chinese/default voice are never used as fallbacks.
    """

    status_changed = Signal(object)
    settings_opened = Signal()

    _PREFERRED_LOCALES = (
        QLocale("en_US"),
        QLocale("en_GB"),
        QLocale("en_AU"),
        QLocale("en_CA"),
    )

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        engine_factory: Callable[..., QTextToSpeech] = QTextToSpeech,
        engine_provider: Callable[[], Iterable[str]] = QTextToSpeech.availableEngines,
        url_opener: Callable[[QUrl], bool] = QDesktopServices.openUrl,
        platform_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine_factory = engine_factory
        self._engine_provider = engine_provider
        self._url_opener = url_opener
        self._platform_name = platform_name or sys.platform
        self._speech: QTextToSpeech | None = None
        self._status = PronunciationStatus(
            available=False,
            message="未检测到英语系统声音，可下载英语语音包。",
        )
        self.refresh()

    @property
    def status(self) -> PronunciationStatus:
        return self._status

    @property
    def available(self) -> bool:
        return self._status.available

    def refresh(self) -> PronunciationStatus:
        """Re-scan installed voices after the user returns from Windows Settings."""
        self.stop()
        previous = self._speech
        self._speech = None
        if previous is not None:
            previous.deleteLater()

        try:
            engines = tuple(self._engine_provider())
        except (AttributeError, OSError, RuntimeError, TypeError):
            engines = ()
        for engine_name in engines:
            normalized_engine = str(engine_name).strip()
            if not normalized_engine or normalized_engine.casefold() == "mock":
                continue
            try:
                speech = self._engine_factory(normalized_engine, self)
            except (AttributeError, OSError, RuntimeError, TypeError):
                continue
            voice = self._find_english_voice(speech)
            if voice is None:
                speech.deleteLater()
                continue
            speech.setVoice(voice)
            self._speech = speech
            status = PronunciationStatus(
                available=True,
                engine=normalized_engine,
                voice_name=voice.name().strip(),
                locale_name=voice.locale().name(),
                message=f"英语发音：{voice.name().strip() or voice.locale().name()}",
            )
            self._publish(status)
            return status

        self._publish(
            PronunciationStatus(
                available=False,
                message="未检测到英语系统声音，可下载英语语音包。",
            )
        )
        return self._status

    def _find_english_voice(self, speech: QTextToSpeech) -> QVoice | None:
        for locale in self._PREFERRED_LOCALES:
            try:
                speech.setLocale(locale)
                voices = tuple(speech.availableVoices())
            except (AttributeError, OSError, RuntimeError, TypeError):
                continue
            for voice in voices:
                if _is_english_voice(voice):
                    return voice
        return None

    def _publish(self, status: PronunciationStatus) -> None:
        self._status = status
        self.status_changed.emit(status)

    def play(self, word: str) -> bool:
        """Start speaking one bounded word without blocking the GUI thread."""
        normalized = " ".join(str(word).split())[:120]
        if not normalized or self._speech is None or not self.available:
            return False
        try:
            self._speech.stop()
            self._speech.say(normalized)
        except (AttributeError, OSError, RuntimeError, TypeError):
            return False
        return True

    def stop(self) -> None:
        if self._speech is None:
            return
        try:
            self._speech.stop()
        except (AttributeError, OSError, RuntimeError, TypeError):
            return

    def open_voice_settings(self) -> bool:
        """Open the official OS language/speech page; never downloads binaries."""
        if not self._platform_name.startswith("win"):
            return False
        opened = self._url_opener(QUrl("ms-settings:regionlanguage"))
        if opened:
            self.settings_opened.emit()
        return bool(opened)
