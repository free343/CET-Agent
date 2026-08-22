from app.ui.theme import APP_STYLESHEET


def test_sidebar_uses_explicit_high_contrast_palette() -> None:
    assert "QFrame#Sidebar { background: #1e1b4b" in APP_STYLESHEET
    assert "color: #e0e7ff" in APP_STYLESHEET
    assert "QFrame#Sidebar QPushButton#NavButton:checked" in APP_STYLESHEET
    assert "background: #4f46e5" in APP_STYLESHEET
    assert "color: #ffffff" in APP_STYLESHEET
