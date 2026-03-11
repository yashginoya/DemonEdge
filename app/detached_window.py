"""DetachedWindow — standalone OS window for a detached dock widget's content.

Created by MainWindow._detach_widget().  Holds the inner content widget of a
BaseWidget and shows it as a fully independent OS-level window.

Title format: "DemonEdge - <Widget Name>"
Closing via the OS X button docks the widget back (does NOT destroy it).
Call force_close() when the terminal is exiting to close for real.
Right-click anywhere in the window for a "Dock back" context menu.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QMenu,
    QVBoxLayout,
    QWidget,
)

_CONTEXT_MENU_QSS = (
    "QMenu { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }"
    "QMenu::item { padding: 4px 16px; }"
    "QMenu::item:selected { background: #30363d; }"
)


class DetachedWindow(QWidget):
    """Standalone OS window wrapping a BaseWidget's inner content widget.

    Parameters
    ----------
    inner_widget:
        The content widget (previously set via QDockWidget.setWidget()) that
        will be re-parented into this window.
    display_name:
        Human-readable widget name used in the OS title bar (e.g. "Watchlist").
    instance_id:
        Unique instance identifier, emitted with dock_back_requested so
        MainWindow can find the correct BaseWidget.
    """

    dock_back_requested = Signal(str)  # instance_id

    def __init__(
        self,
        inner_widget: QWidget,
        display_name: str,
        instance_id: str,
    ) -> None:
        # Qt.Window = independent OS window; stays visible when main window is
        # minimized/loses focus, appears separately in the taskbar.
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(f"DemonEdge - {display_name}")
        self._instance_id = instance_id
        self._inner: QWidget | None = inner_widget
        self._force_closing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Inner content only — no internal toolbar.
        # addWidget re-parents inner_widget from the BaseWidget (QDockWidget)
        # to this DetachedWindow.
        root.addWidget(inner_widget)

    # ------------------------------------------------------------------
    # Public API (called by MainWindow)
    # ------------------------------------------------------------------

    def take_inner(self) -> QWidget:
        """Remove the inner content widget from this window and return it.

        After this call the DetachedWindow is empty.  MainWindow calls
        base_widget.setWidget(inner) immediately afterwards to put it back.
        """
        inner = self._inner
        if inner is None:
            raise RuntimeError("DetachedWindow.take_inner() called twice")
        self.layout().removeWidget(inner)
        inner.setParent(None)  # type: ignore[call-overload]
        self._inner = None
        return inner

    def force_close(self) -> None:
        """Actually close the window.  Called by MainWindow on app exit."""
        self._force_closing = True
        self.close()

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_closing:
            event.accept()
            return
        # Closing via the OS X button → dock the widget back rather than destroy.
        event.ignore()
        self._request_dock_back()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_CONTEXT_MENU_QSS)
        menu.addAction("⬆  Dock back").triggered.connect(self._request_dock_back)
        menu.exec(event.globalPos())

    # ------------------------------------------------------------------

    def _request_dock_back(self) -> None:
        self.dock_back_requested.emit(self._instance_id)
