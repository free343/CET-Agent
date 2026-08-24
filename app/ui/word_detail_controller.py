"""Async coordinator for linked-word detail dialogs."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QObject, QTimer

from app.infrastructure.pronunciation import PronunciationPlayer
from app.services.lexical_fact_view import LinkedWordReference
from app.services.word_detail_service import WordDetailService, WordDetailView
from app.ui.widgets.async_worker import AsyncWorker
from app.ui.word_detail_dialog import WordDetailDialog


class WordDetailController(QObject):
    """Keep dialog navigation responsive and suppress stale worker results."""

    def __init__(
        self,
        service: WordDetailService,
        parent=None,
        *,
        pronunciation_player: PronunciationPlayer | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.pronunciation_player = pronunciation_player
        self.dialog = WordDetailDialog(
            parent,
            pronunciation_player=pronunciation_player,
        )
        self.dialog.linked_word.connect(self._open_nested)
        self.dialog.back_requested.connect(self._go_back)
        self._generation = 0
        self._current_reference: LinkedWordReference | None = None
        self._history: list[LinkedWordReference] = []
        self._workers: set[AsyncWorker] = set()
        self.worker: AsyncWorker | None = None

    def open(self, reference: LinkedWordReference) -> None:
        """Open a fresh root card from a study page."""
        self._history.clear()
        self._start(reference)

    def active_workers(self) -> tuple[AsyncWorker, ...]:
        return tuple(worker for worker in self._workers if worker.isRunning())

    def close(self) -> None:
        if self.pronunciation_player is not None:
            self.pronunciation_player.stop()
        self.dialog.close()

    def _open_nested(self, reference: LinkedWordReference) -> None:
        if self._current_reference is not None:
            self._history.append(self._current_reference)
        self._start(reference)

    def _go_back(self) -> None:
        if not self._history:
            return
        self._start(self._history.pop())

    def _start(self, reference: LinkedWordReference) -> None:
        self._generation += 1
        generation = self._generation
        self._current_reference = reference
        if self.pronunciation_player is not None:
            self.pronunciation_player.stop()
        self.dialog.set_loading(reference.word)
        self.dialog.set_back_enabled(bool(self._history))
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        worker = AsyncWorker(
            partial(self.service.get_word_detail, reference),
            parent=self,
        )
        self._workers.add(worker)
        self.worker = worker
        worker.result_ready.connect(
            lambda result, token=generation: self._loaded(token, result)
        )
        worker.failed.connect(
            lambda message, token=generation: self._failed(token, message)
        )
        worker.finished.connect(partial(self._finished, worker))
        worker.start()

    def _loaded(self, generation: int, result: object) -> None:
        if generation != self._generation:
            return
        if not isinstance(result, WordDetailView):
            self.dialog.set_error("词卡内容格式异常，请稍后重试。")
            return
        self.dialog.set_view(result, can_go_back=bool(self._history))
        if self.pronunciation_player is not None:
            QTimer.singleShot(
                0,
                partial(self._autoplay, generation, result.word),
            )

    def _autoplay(self, generation: int, word: str) -> None:
        if (
            generation != self._generation
            or not self.dialog.isVisible()
            or self.pronunciation_player is None
        ):
            return
        self.pronunciation_player.play(word)

    def _failed(self, generation: int, message: str) -> None:
        if generation == self._generation:
            self.dialog.set_error(message)

    def _finished(self, worker: AsyncWorker) -> None:
        self._workers.discard(worker)
        if self.worker is worker:
            self.worker = None
        worker.setParent(None)
        worker.deleteLater()
        worker.deleteLater()
