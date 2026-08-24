"""Small rich-text label that exposes safe in-app lexical links."""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel

from app.services.lexical_fact_view import LinkedWordReference


class LexicalLinkLabel(QLabel):
    """Render bounded lexical items and emit only local target references."""

    linked_word_clicked = Signal(object)

    def __init__(
        self,
        text: str = "",
        *,
        on_linked_word: Callable[[LinkedWordReference], None] | None = None,
    ) -> None:
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._references: dict[str, LinkedWordReference] = {}
        self.linkActivated.connect(self._link_activated)
        if on_linked_word is not None:
            self.linked_word_clicked.connect(on_linked_word)

    def set_items(
        self,
        items: Sequence[str],
        references: Sequence[LinkedWordReference | None] = (),
    ) -> None:
        self._references.clear()
        lines: list[str] = []
        for index, raw_item in enumerate(items[:8]):
            text = str(raw_item).strip()[:240]
            if not text:
                continue
            reference = references[index] if index < len(references) else None
            lines.append(self._render_item(text, reference))
        self.setText("<br>".join(lines))

    def set_plain_text(self, text: str) -> None:
        self._references.clear()
        self.setText(html.escape(str(text)).replace("\n", "<br>"))

    def _render_item(
        self,
        text: str,
        reference: LinkedWordReference | None,
    ) -> str:
        escaped = html.escape(text)
        if reference is None:
            return escaped
        target = html.escape(reference.word.strip())
        if not target:
            return escaped
        position = escaped.casefold().find(target.casefold())
        if position < 0:
            return escaped
        encoded = quote(reference.word, safe="")
        href = f"word:{encoded}"
        self._references[encoded] = reference
        anchor = (
            f'<a href="{html.escape(href, quote=True)}" '
            'style="color:#2563eb; text-decoration:underline;">'
            f"{escaped[position : position + len(target)]}</a>"
        )
        return escaped[:position] + anchor + escaped[position + len(target) :]

    def _link_activated(self, href: str) -> None:
        if not href.startswith("word:"):
            return
        encoded = href.removeprefix("word:")
        reference = self._references.get(encoded)
        if reference is None:
            # QLabel may normalize a percent-encoded href; retain a strict
            # local-only fallback without ever opening an external URL.
            decoded = unquote(encoded)
            reference = next(
                (
                    value
                    for key, value in self._references.items()
                    if unquote(key) == decoded
                ),
                None,
            )
        if reference is not None:
            self.linked_word_clicked.emit(reference)
