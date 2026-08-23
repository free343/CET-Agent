from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QScrollArea

from app.config import ENV_FILE, Settings
from app.ui.settings_page import SettingsPage


def test_settings_page_exposes_deepseek_channel_without_rendering_secret() -> None:
    app = QApplication.instance() or QApplication([])
    secret = "advanced-secret-must-not-render"
    page = SettingsPage(
        Settings(
            advanced_llm_provider="openai-compatible",
            advanced_llm_model="deepseek-v4-flash",
            advanced_llm_base_url="https://api.deepseek.com",
            advanced_llm_api_key=secret,
        )
    )

    rendered = "\n".join(
        [label.text() for label in page.findChildren(QLabel)]
        + [editor.toPlainText() for editor in page.findChildren(QPlainTextEdit)]
    )

    assert "高级模型配置通道" in rendered
    assert "deepseek-v4-flash" in rendered
    assert "ADVANCED_LLM_PROVIDER=openai-compatible" in rendered
    assert str(ENV_FILE) in rendered
    assert "已配置（内容已隐藏）" in rendered
    assert secret not in rendered
    page.resize(520, 420)
    page.show()
    app.processEvents()
    scroll = page.findChild(QScrollArea, "SettingsScroll")
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0
    page.deleteLater()
    app.processEvents()
