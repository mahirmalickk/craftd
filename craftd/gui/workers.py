"""Run slow work (network, hashing) off the UI thread so the window never freezes."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..log import log


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], args: tuple):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn(self.signals.progress.emit, *self.args)
        except Exception as exc:  # report every failure to the UI instead of crashing
            # into craftd.log, not the console: Craftd.exe has none (printing there could even fail)
            if getattr(exc, "expected", False):  # e.g. sign-in declined: one line, no traceback
                log.warning("%s", exc)
            else:
                log.exception("Background task failed: %s", getattr(self.fn, "__qualname__", self.fn))
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.done.emit(result)


class Runner(QObject):
    """Starts background tasks. `fn` always receives a progress(str) callback first."""

    busy_changed = Signal(bool)

    def __init__(self, status: Callable[[str], None], on_error: Callable[[str], None]):
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self.status = status
        self.default_error = on_error
        self.active: set[_Task] = set()

    def run(self, fn: Callable[..., Any], *args, on_done: Callable[[Any], None] | None = None,
            on_error: Callable[[str], None] | None = None, progress: Callable[[str], None] | None = None) -> None:
        task = _Task(fn, args)
        self.active.add(task)
        task.signals.progress.connect(progress or self.status)

        def finished(result):
            self._release(task)
            if on_done:
                on_done(result)

        def failed(message):
            self._release(task)
            (on_error or self.default_error)(message)

        task.signals.done.connect(finished)
        task.signals.failed.connect(failed)
        if len(self.active) == 1:
            self.busy_changed.emit(True)
        self.pool.start(task)

    def _release(self, task: _Task) -> None:
        self.active.discard(task)
        if not self.active:
            self.busy_changed.emit(False)
            self.status("Ready")

    def wait(self, msecs: int = 30000) -> bool:
        return self.pool.waitForDone(msecs)
