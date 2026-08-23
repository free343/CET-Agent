"""Reusable presentation widget for deterministic English choices."""

from __future__ import annotations

import textwrap

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout

from app.domain.acquisition import EnglishOption


class EnglishQuizWidget(QFrame):
    option_selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.options: tuple[EnglishOption, ...] = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(8)
        self.help_label = QLabel("选择最符合例句语境的英语单词。")
        self.help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.help_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self.help_label)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.buttons: list[QPushButton] = []
        for index in range(4):
            button = QPushButton("")
            button.setObjectName("ChoiceButton")
            button.setMinimumHeight(54)
            button.clicked.connect(
                lambda _checked=False, value=index: self.option_selected.emit(value)
            )
            self.buttons.append(button)
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        self.reset()

    def set_options(self, options: tuple[EnglishOption, ...]) -> bool:
        self.reset()
        if len(options) != 4:
            return False
        self.options = options
        for index, (button, option) in enumerate(
            zip(self.buttons, options, strict=True)
        ):
            button.setText(self._choice_label(index, option.text))
            button.setEnabled(True)
        self.show()
        return True

    def option(self, index: int) -> EnglishOption | None:
        if not 0 <= index < len(self.options) or not self.buttons[index].isEnabled():
            return None
        return self.options[index]

    def choose_with_number(self, index: int) -> bool:
        if self.isHidden() or self.option(index) is None:
            return False
        self.buttons[index].click()
        return True

    def disable_and_highlight(self, selected_index: int | None = None) -> None:
        for index, (button, option) in enumerate(
            zip(self.buttons, self.options, strict=False)
        ):
            button.setEnabled(False)
            if option.is_correct:
                button.setStyleSheet(
                    "background: #dcfce7; border: 1px solid #16a34a; color: #166534;"
                )
            elif selected_index == index:
                button.setStyleSheet(
                    "background: #fee2e2; border: 1px solid #dc2626; color: #991b1b;"
                )

    def reset(self) -> None:
        self.options = ()
        self.help_label.setText("选择最符合例句语境的英语单词。")
        for button in self.buttons:
            button.setEnabled(False)
            button.setStyleSheet("")
        self.hide()

    @staticmethod
    def _choice_label(index: int, text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) > 90:
            compact = compact[:89].rstrip() + "…"
        wrapped = "\n".join(textwrap.wrap(compact, width=36))
        return f"{index + 1}. {wrapped}"
