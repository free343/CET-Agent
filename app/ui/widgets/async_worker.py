"""Tiny QThread wrapper keeping model/network work off the UI thread."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class AsyncWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, function: Callable[..., Any], *args: Any, parent=None) -> None:
        super().__init__(parent)
        self.function = function
        self.args = args

    def run(self) -> None:
        try:
            self.result_ready.emit(self.function(*self.args))
        except Exception as exc:
            logger.exception("Asynchronous UI task failed")
            self.failed.emit(str(exc))
