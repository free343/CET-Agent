from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.widgets.async_worker import AsyncWorker


def test_async_worker_does_not_expose_internal_exception_text() -> None:
    app = QApplication.instance() or QApplication([])
    messages: list[str] = []

    def fail() -> None:
        raise RuntimeError("secret path and SQL details")

    worker = AsyncWorker(fail)
    worker.failed.connect(messages.append)
    worker.start()
    assert worker.wait(2_000)
    app.processEvents()

    assert messages == ["后台任务执行失败，请稍后重试。"]
    assert "secret" not in messages[0]
    worker.deleteLater()
