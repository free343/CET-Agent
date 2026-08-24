"""Small reusable controls for local word pronunciation."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _status_value(player: Any, name: str, default: Any = None) -> Any:
    status = getattr(player, "status", None)
    return getattr(status, name, default)


class PronunciationPlayButton(QPushButton):
    """A compact button that speaks only the currently displayed word."""

    def __init__(self, player: Any | None, parent: QWidget | None = None) -> None:
        super().__init__("🔊", parent)
        self.player = player
        self._word = ""
        self._requested_enabled = False
        self.setObjectName("PronunciationButton")
        self.setAccessibleName("播放单词读音")
        self.setToolTip("播放单词读音")
        self.setFixedWidth(42)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.clicked.connect(self._play)
        signal = getattr(player, "status_changed", None)
        if signal is not None:
            signal.connect(self._status_changed)
        if player is None:
            self.hide()
        self._status_changed(getattr(player, "status", None))

    def set_word(self, word: str, *, enabled: bool = True) -> None:
        normalized = " ".join(str(word).split())[:120]
        if (
            self._word
            and normalized
            and normalized.casefold() != self._word.casefold()
            and self.player is not None
        ):
            stop = getattr(self.player, "stop", None)
            if callable(stop):
                stop()
        self._word = normalized
        self._requested_enabled = bool(enabled)
        self._refresh_enabled()

    def clear_word(self) -> None:
        if self._word and self.player is not None:
            stop = getattr(self.player, "stop", None)
            if callable(stop):
                stop()
        self.set_word("", enabled=False)

    def _status_changed(self, _status: object) -> None:
        self._refresh_enabled()
        message = str(_status_value(self.player, "message", "") or "").strip()
        if message:
            self.setToolTip(
                message if not self._word else f"播放 {self._word}；{message}"
            )

    def _refresh_enabled(self) -> None:
        available = bool(_status_value(self.player, "available", True))
        self.setEnabled(bool(self._word) and self._requested_enabled and available)

    def _play(self) -> None:
        if self._word and self.player is not None:
            self.player.play(self._word)


class PronunciationInstallButton(QPushButton):
    """One-click handoff to the official OS voice installation page."""

    def __init__(self, player: Any | None, parent: QWidget | None = None) -> None:
        super().__init__("下载英语语音包", parent)
        self.player = player
        self.setObjectName("PronunciationInstallButton")
        self.setAccessibleName("打开英语语音包设置")
        self.setToolTip("打开系统语言设置，安装英语语音包")
        self.clicked.connect(self._open_settings)
        signal = getattr(player, "status_changed", None)
        if signal is not None:
            signal.connect(self._status_changed)
        if player is None:
            self.hide()
        self._status_changed(getattr(player, "status", None))

    def _status_changed(self, _status: object) -> None:
        available = bool(_status_value(self.player, "available", True))
        self.setVisible(self.player is not None and not available)
        self.setEnabled(self.player is not None)

    def _open_settings(self) -> None:
        if self.player is None:
            return
        self.player.open_voice_settings()


class PronunciationListRow(QWidget):
    """A list row with the legacy text item retained for selection/tests."""

    def __init__(
        self,
        word: str,
        phonetic: str,
        body: str,
        player: Any | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PronunciationListRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(10)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        word_label = QLabel(word)
        word_label.setObjectName("PronunciationListWord")
        heading.addWidget(word_label)
        if phonetic:
            phonetic_label = QLabel(phonetic)
            phonetic_label.setObjectName("PronunciationListPhonetic")
            heading.addWidget(phonetic_label)
        heading.addStretch()
        text_column.addLayout(heading)
        body_label = QLabel(body)
        body_label.setObjectName("PronunciationListBody")
        body_label.setWordWrap(True)
        text_column.addWidget(body_label)
        layout.addLayout(text_column, 1)
        button = PronunciationPlayButton(player, self)
        button.set_word(word)
        self.play_button = button
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignTop)
