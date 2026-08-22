"""Desktop notification adapters with an actionable Windows toast backend."""

from __future__ import annotations

import importlib
import logging
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon, QWidget

logger = logging.getLogger(__name__)

START_REVIEW_ACTION = "action=start_review"
SNOOZE_ACTION = "action=snooze"
APP_USER_MODEL_ID = "CET.Agent.Desktop"
START_MENU_SHORTCUT = Path("Microsoft/Windows/Start Menu/Programs/CET-Agent.lnk")
INSTALL_MARKER_NAME = ".cet-agent-installed"


class NotificationAdapter(ABC):
    @abstractmethod
    def notify(self, due_word_count: int, estimated_minutes: int) -> None:
        pass


class ToastBackend(Protocol):
    def notify(self, due_word_count: int, estimated_minutes: int) -> None: ...

    def close(self) -> None: ...


class NotificationActionBridge(QObject):
    """Marshal native notification callbacks onto the Qt application thread."""

    start_requested = Signal()
    snooze_requested = Signal()
    _native_action_received = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._native_action_received.connect(
            self._dispatch_native_action,
            Qt.ConnectionType.QueuedConnection,
        )

    @Slot()
    def request_start(self) -> None:
        self.start_requested.emit()

    def dispatch_native_action(self, arguments: str | None) -> None:
        self._native_action_received.emit(arguments)

    @Slot(object)
    def _dispatch_native_action(self, arguments: object) -> None:
        if arguments == SNOOZE_ACTION:
            self.snooze_requested.emit()
            return
        # A toast body click returns the toast tag rather than a fixed action.
        # Treat every non-snooze activation from this private callback as Start.
        self.start_requested.emit()


class WindowsToastBackend:
    """Windows-Toasts wrapper kept independent from the Qt tray fallback."""

    def __init__(
        self,
        action_handler: Callable[[str | None], None],
        *,
        toast_module: Any | None = None,
        notifier_aumid: str | None = None,
    ) -> None:
        module = toast_module or importlib.import_module("windows_toasts")
        self._toast_type = module.Toast
        self._button_type = module.ToastButton
        self._action_handler = action_handler
        if notifier_aumid is None:
            self._toaster = module.InteractableWindowsToaster("CET-Agent")
        else:
            self._toaster = module.InteractableWindowsToaster(
                "CET-Agent",
                notifier_aumid,
            )
        self._active_toasts: dict[str, Any] = {}
        logger.info(
            "Native Windows toast backend initialized identity=%s",
            "installed" if notifier_aumid else "portable",
        )

    def notify(self, due_word_count: int, estimated_minutes: int) -> None:
        toast = self._toast_type(
            [
                "CET-Agent 复习提醒",
                (
                    f"你有 {due_word_count} 个单词进入复习窗口\n预计需要 "
                    f"{estimated_minutes} 分钟"
                ),
            ],
            actions=(
                self._button_type("开始复习", START_REVIEW_ACTION),
                self._button_type("30 分钟后提醒", SNOOZE_ACTION),
            ),
        )
        toast.on_activated = lambda event: self._on_activated(toast, event)
        toast.on_failed = lambda event: self._on_failed(toast, event)
        self._active_toasts[toast.tag] = toast
        try:
            self._toaster.show_toast(toast)
        except Exception:
            self._forget_toast(toast)
            raise

    def close(self) -> None:
        # A process can coexist with another source, portable, or installed
        # instance. Never clear an entire AUMID; remove only this process's
        # tracked Toasts so closing one window cannot erase another's reminder.
        for toast in tuple(self._active_toasts.values()):
            try:
                self._toaster.remove_toast(toast)
            except Exception:
                logger.debug("Native toast was already absent", exc_info=True)
        self._active_toasts.clear()

    def _on_activated(self, toast: Any, event: Any) -> None:
        self._forget_toast(toast)
        self._action_handler(getattr(event, "arguments", None))

    def _on_failed(self, toast: Any, event: Any) -> None:
        self._forget_toast(toast)
        logger.error(
            "Native Windows toast failed error_code=%s",
            getattr(event, "error_code", "unknown"),
        )

    def _forget_toast(self, toast: Any) -> None:
        self._active_toasts.pop(toast.tag, None)


def create_windows_toast_backend(
    action_handler: Callable[[str | None], None],
) -> ToastBackend | None:
    if sys.platform != "win32":
        return None
    try:
        return WindowsToastBackend(
            action_handler,
            notifier_aumid=installed_toast_aumid(),
        )
    except Exception:
        logger.exception(
            "Native Windows toast backend unavailable; using Qt tray fallback"
        )
        return None


def installed_toast_aumid(
    environ: Mapping[str, str] | None = None,
    *,
    executable: Path | None = None,
    frozen: bool | None = None,
) -> str | None:
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return None
    executable_path = Path(sys.executable) if executable is None else executable
    marker = executable_path.resolve().parent / INSTALL_MARKER_NAME
    try:
        if marker.read_text(encoding="utf-8").strip() != APP_USER_MODEL_ID:
            return None
    except OSError:
        return None
    environment = os.environ if environ is None else environ
    app_data = environment.get("APPDATA", "").strip()
    if not app_data:
        return None
    shortcut = Path(app_data) / START_MENU_SHORTCUT
    return APP_USER_MODEL_ID if shortcut.is_file() else None


class QtNotificationAdapter(NotificationAdapter):
    """Own the tray icon and prefer native actionable toasts when available."""

    def __init__(
        self,
        parent: QWidget,
        on_activated: Callable[[], None],
        on_snooze: Callable[[], None],
        *,
        toast_backend: ToastBackend | None = None,
    ) -> None:
        self.action_bridge = NotificationActionBridge(parent)
        self.action_bridge.start_requested.connect(on_activated)
        self.action_bridge.snooze_requested.connect(on_snooze)
        self.toast_backend = (
            toast_backend
            if toast_backend is not None
            else create_windows_toast_backend(self.action_bridge.dispatch_native_action)
        )
        self.tray = QSystemTrayIcon(parent)
        icon = QApplication.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxInformation
        )
        self.tray.setIcon(icon)
        self.tray.setToolTip("CET-Agent")
        self.tray.messageClicked.connect(self.action_bridge.request_start)
        self.tray.show()

    def notify(self, due_word_count: int, estimated_minutes: int) -> None:
        if self.toast_backend is not None:
            try:
                self.toast_backend.notify(due_word_count, estimated_minutes)
                return
            except Exception:
                logger.exception(
                    "Native Windows toast send failed; using Qt tray fallback"
                )
                self._close_toast_backend()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray.showMessage(
            "CET-Agent 复习提醒",
            f"你有 {due_word_count} 个单词进入复习窗口\n"
            f"预计需要 {estimated_minutes} 分钟",
            QSystemTrayIcon.MessageIcon.Information,
            10_000,
        )

    def close(self) -> None:
        self._close_toast_backend()
        self.tray.hide()

    def _close_toast_backend(self) -> None:
        backend = self.toast_backend
        self.toast_backend = None
        if backend is None:
            return
        try:
            backend.close()
        except Exception:
            logger.exception("Failed to clear native Windows toasts")
