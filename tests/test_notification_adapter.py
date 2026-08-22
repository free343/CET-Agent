from __future__ import annotations

import os
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from app.infrastructure.notification_adapter import (
    APP_USER_MODEL_ID,
    INSTALL_MARKER_NAME,
    SNOOZE_ACTION,
    START_MENU_SHORTCUT,
    START_REVIEW_ACTION,
    NotificationActionBridge,
    QtNotificationAdapter,
    WindowsToastBackend,
    installed_toast_aumid,
)


class FakeToast:
    next_tag = 0

    def __init__(self, text_fields, **kwargs) -> None:
        type(self).next_tag += 1
        self.tag = f"toast-{self.next_tag}"
        self.text_fields = text_fields
        self.actions = kwargs["actions"]
        self.on_activated = kwargs.get("on_activated")
        self.on_dismissed = kwargs.get("on_dismissed")
        self.on_failed = kwargs.get("on_failed")


class FakeToastButton:
    def __init__(self, content: str, arguments: str) -> None:
        self.content = content
        self.arguments = arguments


class FakeToaster:
    def __init__(self, application_text: str) -> None:
        self.application_text = application_text
        self.shown = []
        self.removed = []
        self.clear_count = 0

    def show_toast(self, toast) -> None:
        self.shown.append(toast)

    def remove_toast(self, toast) -> None:
        self.removed.append(toast)

    def clear_toasts(self) -> None:
        self.clear_count += 1


class FakeToastModule:
    Toast = FakeToast
    ToastButton = FakeToastButton

    def __init__(self) -> None:
        self.toaster = None

    def InteractableWindowsToaster(
        self,
        application_text: str,
        notifier_aumid: str | None = None,
    ):
        self.toaster = FakeToaster(application_text)
        self.toaster.notifier_aumid = notifier_aumid
        return self.toaster


class FailingBackend:
    def __init__(self) -> None:
        self.close_count = 0

    @staticmethod
    def notify(_due_word_count: int, _estimated_minutes: int) -> None:
        raise RuntimeError("toast failed")

    def close(self) -> None:
        self.close_count += 1


def test_windows_toast_contains_actions_and_dispatches_activation() -> None:
    module = FakeToastModule()
    actions: list[str | None] = []
    backend = WindowsToastBackend(actions.append, toast_module=module)

    backend.notify(12, 4)

    assert module.toaster is not None
    assert module.toaster.application_text == "CET-Agent"
    assert len(module.toaster.shown) == 1
    toast = module.toaster.shown[0]
    assert toast.text_fields == [
        "CET-Agent 复习提醒",
        "你有 12 个单词进入复习窗口\n预计需要 4 分钟",
    ]
    assert [(button.content, button.arguments) for button in toast.actions] == [
        ("开始复习", START_REVIEW_ACTION),
        ("30 分钟后提醒", SNOOZE_ACTION),
    ]

    toast.on_activated(SimpleNamespace(arguments=SNOOZE_ACTION))
    toast.on_activated(SimpleNamespace(arguments=START_REVIEW_ACTION))
    assert actions == [SNOOZE_ACTION, START_REVIEW_ACTION]

    backend.notify(3, 1)
    second_toast = module.toaster.shown[1]
    backend.close()
    assert module.toaster.removed == [second_toast]


def test_action_bridge_routes_snooze_and_body_click() -> None:
    app = QApplication.instance() or QApplication([])
    bridge = NotificationActionBridge()
    ui_thread = threading.get_ident()
    started_on: list[int] = []
    snoozed_on: list[int] = []
    bridge.start_requested.connect(lambda: started_on.append(threading.get_ident()))
    bridge.snooze_requested.connect(lambda: snoozed_on.append(threading.get_ident()))

    thread = threading.Thread(
        target=lambda: (
            bridge.dispatch_native_action(SNOOZE_ACTION),
            bridge.dispatch_native_action("generated-toast-tag"),
        )
    )
    thread.start()
    thread.join()
    app.processEvents()

    assert started_on == [ui_thread]
    assert snoozed_on == [ui_thread]
    bridge.deleteLater()


def test_installed_shortcut_selects_dedicated_notification_identity(
    tmp_path,
) -> None:
    environment = {"APPDATA": str(tmp_path)}
    executable = tmp_path / "Programs" / "CET-Agent" / "CET-Agent.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    marker = executable.parent / INSTALL_MARKER_NAME
    marker.write_text(APP_USER_MODEL_ID, encoding="utf-8")
    assert (
        installed_toast_aumid(
            environment,
            executable=executable,
            frozen=False,
        )
        is None
    )
    assert (
        installed_toast_aumid(
            environment,
            executable=executable,
            frozen=True,
        )
        is None
    )

    shortcut = tmp_path / START_MENU_SHORTCUT
    shortcut.parent.mkdir(parents=True)
    shortcut.touch()

    assert (
        installed_toast_aumid(
            environment,
            executable=executable,
            frozen=True,
        )
        == APP_USER_MODEL_ID
    )
    module = FakeToastModule()
    backend = WindowsToastBackend(
        lambda _action: None,
        toast_module=module,
        notifier_aumid=APP_USER_MODEL_ID,
    )
    assert module.toaster is not None
    assert module.toaster.notifier_aumid == APP_USER_MODEL_ID
    backend.notify(2, 1)
    toast = module.toaster.shown[0]
    backend.close()
    assert module.toaster.clear_count == 0
    assert module.toaster.removed == [toast]


def test_qt_adapter_disables_failed_backend_before_tray_fallback(
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    backend = FailingBackend()
    adapter = QtNotificationAdapter(
        parent,
        lambda: None,
        lambda: None,
        toast_backend=backend,
    )
    shown: list[tuple] = []
    monkeypatch.setattr(
        adapter.tray,
        "showMessage",
        lambda *args: shown.append(args),
    )
    monkeypatch.setattr(
        QSystemTrayIcon,
        "isSystemTrayAvailable",
        lambda: True,
    )

    adapter.notify(5, 2)
    app.processEvents()

    assert backend.close_count == 1
    assert adapter.toast_backend is None
    assert len(shown) == 1
    adapter.close()
    parent.deleteLater()
