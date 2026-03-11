"""QtLogHandler — singleton logging.Handler that emits a Qt signal per record.

Install via install_qt_handler() after QApplication is created.  Records are
buffered in a deque so widgets created mid-session can replay them on open.
"""
from __future__ import annotations

import collections
import logging

from PySide6.QtCore import QObject, Signal


class _SignalEmitter(QObject):
    record_emitted: Signal = Signal(object)  # logging.LogRecord


class QtLogHandler(logging.Handler):
    """Singleton handler.  Safe to call from non-Qt threads — PySide6 queues
    the signal automatically when the receiver lives on the main thread."""

    _instance: "QtLogHandler | None" = None

    def __new__(cls) -> "QtLogHandler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_qt_initialized"):
            return
        super().__init__()
        self._qt_initialized = True
        self._emitter = _SignalEmitter()
        # Public signal — widgets connect to this
        self.record_emitted: Signal = self._emitter.record_emitted
        # Ring buffer (newest entries survive when full)
        self._buffer: collections.deque[logging.LogRecord] = collections.deque(maxlen=5000)

    @classmethod
    def instance(cls) -> "QtLogHandler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # logging.Handler interface
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append(record)
        try:
            self._emitter.record_emitted.emit(record)
        except Exception:  # noqa: BLE001 — never let handler crash the app
            pass

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @property
    def buffer(self) -> collections.deque[logging.LogRecord]:
        return self._buffer


def install_qt_handler() -> None:
    """Add QtLogHandler to the root logger.  Call after QApplication is created."""
    root = logging.getLogger()
    handler = QtLogHandler.instance()
    if handler not in root.handlers:
        root.addHandler(handler)
