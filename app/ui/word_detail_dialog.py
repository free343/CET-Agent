"""Read-only modal word-card presentation for linked lexical targets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.lexical_fact_view import LinkedWordReference
from app.services.word_detail_service import WordDetailView
from app.ui.widgets.lexical_link_label import LexicalLinkLabel


class WordDetailDialog(QDialog):
    """Scrollable, non-editing card that never owns learning state."""

    linked_word = Signal(object)
    back_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("词卡详情")
        self.resize(760, 620)
        self.setMinimumSize(480, 400)
        self.setModal(False)
        self.setObjectName("WordDetailDialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        header = QHBoxLayout()
        self.back_button = QPushButton("‹ 返回")
        self.back_button.setObjectName("WordDetailBackButton")
        self.back_button.setAccessibleName("返回上一张词卡")
        self.back_button.setToolTip("返回上一张词卡（Alt+Left）")
        self.back_button.clicked.connect(self.back_requested.emit)
        self.back_button.hide()
        header.addWidget(self.back_button)
        self.word_label = QLabel("")
        self.word_label.setObjectName("WordDetailWord")
        header.addWidget(self.word_label)
        header.addStretch()
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("WordDetailCloseButton")
        self.close_button.setAccessibleName("关闭词卡详情")
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button)
        outer.addLayout(header)

        self.phonetic_label = QLabel("")
        self.phonetic_label.setObjectName("WordDetailPhonetic")
        self.meaning_label = QLabel("")
        self.meaning_label.setObjectName("WordDetailMeaning")
        self.meaning_label.setWordWrap(True)
        self.level_label = QLabel("")
        self.level_label.setObjectName("WordDetailLevel")
        self.status_label = QLabel("")
        self.status_label.setObjectName("WordDetailStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.phonetic_label)
        outer.addWidget(self.meaning_label)
        outer.addWidget(self.level_label)
        outer.addWidget(self.status_label)

        self.comparison_frame = QFrame()
        self.comparison_frame.setObjectName("WordDetailComparison")
        comparison_layout = QHBoxLayout(self.comparison_frame)
        comparison_layout.setContentsMargins(10, 8, 10, 8)
        comparison_layout.setSpacing(18)
        source_column = QVBoxLayout()
        source_title = QLabel("来源词")
        source_title.setObjectName("WordDetailComparisonTitle")
        self.origin_word_label = QLabel("")
        self.origin_word_label.setObjectName("WordDetailComparisonWord")
        self.origin_meaning_label = QLabel("")
        self.origin_meaning_label.setWordWrap(True)
        source_column.addWidget(source_title)
        source_column.addWidget(self.origin_word_label)
        source_column.addWidget(self.origin_meaning_label)
        target_column = QVBoxLayout()
        target_title = QLabel("当前词")
        target_title.setObjectName("WordDetailComparisonTitle")
        self.target_word_label = QLabel("")
        self.target_word_label.setObjectName("WordDetailComparisonWord")
        self.target_meaning_label = QLabel("")
        self.target_meaning_label.setWordWrap(True)
        target_column.addWidget(target_title)
        target_column.addWidget(self.target_word_label)
        target_column.addWidget(self.target_meaning_label)
        comparison_layout.addLayout(source_column, 1)
        comparison_layout.addLayout(target_column, 1)
        self.comparison_frame.hide()
        outer.addWidget(self.comparison_frame)

        self._focus_word = ""
        self._link_labels: list[tuple[LexicalLinkLabel, tuple[str, ...]]] = []
        QShortcut(QKeySequence("Alt+Left"), self, self.back_requested.emit).setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )

        self.scroll = QScrollArea()
        self.scroll.setObjectName("WordDetailScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 4, 12, 4)
        self.content_layout.setSpacing(14)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)

        self.loading_label = QLabel("")
        self.loading_label.setObjectName("WordDetailLoading")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.hide()
        outer.addWidget(self.loading_label)

    def set_loading(self, word: str) -> None:
        self.word_label.setText(str(word).strip())
        self.phonetic_label.clear()
        self.meaning_label.clear()
        self.level_label.clear()
        self.status_label.clear()
        self.comparison_frame.hide()
        self._link_labels.clear()
        self._clear_content()
        self.scroll.hide()
        self.loading_label.setText("正在加载词卡…")
        self.loading_label.show()

    def set_error(self, message: str) -> None:
        self._clear_content()
        self.scroll.hide()
        self.loading_label.setText(str(message).strip() or "词卡暂时无法打开。")
        self.loading_label.show()
        self.status_label.clear()
        self.comparison_frame.hide()
        self._link_labels.clear()

    def set_view(self, view: WordDetailView, *, can_go_back: bool = False) -> None:
        self.word_label.setText(view.word)
        self.phonetic_label.setText(view.phonetic)
        self.meaning_label.setText(view.meaning or "暂无中文释义")
        self.level_label.setText(view.level)
        self.status_label.setText(view.trust_label)
        self.status_label.setVisible(bool(view.trust_label))
        origin_word = view.reference.origin_word.strip()
        if origin_word and origin_word.casefold() != view.word.casefold():
            self.origin_word_label.setText(origin_word)
            self.origin_meaning_label.setText(
                view.reference.origin_meaning.strip() or "暂无中文释义"
            )
            self.target_word_label.setText(view.word)
            self.target_meaning_label.setText(view.meaning or "暂无中文释义")
            self.comparison_frame.setToolTip(
                f"{view.reference.origin_relation or '关联'}：{origin_word} → {view.word}"
            )
            self.comparison_frame.show()
        else:
            self.comparison_frame.hide()
        self.back_button.setVisible(can_go_back)
        self._link_labels.clear()
        self._clear_content()
        if view.reference_only and view.reference.english_definition:
            self._add_text_block("英文释义", view.reference.english_definition)
        if view.example:
            self._add_text_block("例句", view.example)
        if view.example_translation:
            self._add_text_block("例句翻译", view.example_translation)
        for section in view.sections:
            if not section.items:
                continue
            title = QLabel(f"{section.title} · {section.status}")
            title.setObjectName("WordDetailSectionTitle")
            self.content_layout.addWidget(title)
            label = LexicalLinkLabel()
            label.setWordWrap(True)
            label.linked_word_clicked.connect(self._remember_link_focus)
            label.linked_word_clicked.connect(self.linked_word.emit)
            label.set_items(section.items, section.item_references)
            references = tuple(
                reference.word if reference is not None else ""
                for reference in section.item_references
            )
            self._link_labels.append((label, references))
            self.content_layout.addWidget(label)
        self.content_layout.addStretch()
        self.loading_label.hide()
        self.scroll.show()
        self._focus_link(self._focus_word)

    def set_back_enabled(self, enabled: bool) -> None:
        self.back_button.setVisible(enabled)

    def _remember_link_focus(self, reference: object) -> None:
        if isinstance(reference, LinkedWordReference):
            self._focus_word = reference.word.strip()

    def _focus_link(self, word: str) -> None:
        target = str(word or "").strip().casefold()
        if not target:
            return
        for label, words in self._link_labels:
            if any(candidate.strip().casefold() == target for candidate in words):
                label.setFocus(Qt.FocusReason.OtherFocusReason)
                return

    def _add_text_block(self, title: str, text: str) -> None:
        title_label = QLabel(title)
        title_label.setObjectName("WordDetailSectionTitle")
        text_label = QLabel(str(text).strip())
        text_label.setWordWrap(True)
        text_label.setObjectName("WordDetailText")
        self.content_layout.addWidget(title_label)
        self.content_layout.addWidget(text_label)

    def _clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
