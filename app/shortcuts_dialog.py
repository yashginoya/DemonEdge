"""Keyboard Shortcuts reference window (Help → Keyboard Shortcuts, Ctrl+/).

This is a persistent non-modal QWidget window.  Closing it (X button or the
Close button) hides it rather than destroying it; the single instance is
reused on subsequent opens.  It stays visible when the main terminal window
loses focus because its parent is None.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Shortcut data — single source of truth
# Keep in sync with _register_shortcuts() in main_window.py.
# ---------------------------------------------------------------------------

_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Widgets",
        [
            ("New Watchlist", "Ctrl+W"),
            ("New Option Chain", "Ctrl+O"),
            ("New Positions & P&L", "Ctrl+P"),
            ("Open Log Viewer", "Ctrl+L"),
            ("New Market Depth", "F5"),
        ],
    ),
    (
        "General",
        [
            ("Command Palette", "Ctrl+K"),
            ("Save Layout", "Ctrl+Shift+S"),
            ("Keyboard Shortcuts", "Ctrl+/"),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Stylesheets
# ---------------------------------------------------------------------------

_WINDOW_QSS = """
KeyboardShortcutsWindow {
    background: #0d1117;
}
QLabel {
    color: #e6edf3;
}
"""

_SECTION_HEADER_QSS = (
    "color: #8b949e;"
    " font-size: 11px;"
    " font-weight: bold;"
    " letter-spacing: 0.8px;"
    " text-transform: uppercase;"
    " padding: 0 0 4px 0;"
)

_ACTION_QSS = "color: #c9d1d9; font-size: 13px;"

_SHORTCUT_QSS = (
    "color: #58a6ff;"
    " font-family: 'Consolas', 'Courier New', monospace;"
    " font-size: 12px;"
    " background: #161b22;"
    " border: 1px solid #30363d;"
    " border-radius: 4px;"
    " padding: 2px 7px;"
)

_DIVIDER_QSS = "background: #21262d;"

_CLOSE_BTN_QSS = (
    "QPushButton {"
    "  background: #21262d;"
    "  color: #c9d1d9;"
    "  border: 1px solid #30363d;"
    "  border-radius: 6px;"
    "  font-size: 13px;"
    "  padding: 6px 24px;"
    "}"
    "QPushButton:hover {"
    "  background: #30363d;"
    "  color: #e6edf3;"
    "}"
    "QPushButton:pressed {"
    "  background: #161b22;"
    "}"
)


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(_DIVIDER_QSS)
    return line


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


class KeyboardShortcutsWindow(QWidget):
    """Non-modal, persistent reference window for keyboard shortcuts.

    * Parent is None — independent of the main window; stays visible when
      the terminal loses focus.
    * closeEvent hides rather than destroys; the instance is reused.
    * Call show_or_raise() to open or bring to front.
    """

    def __init__(self) -> None:
        # No parent → independent OS window; Qt.Window gives it a title bar.
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setFixedSize(400, 390)
        self.setStyleSheet(_WINDOW_QSS)
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_or_raise(self) -> None:
        """Show the window if hidden, or bring it to front if already open."""
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(0)

        for i, (section_title, rows) in enumerate(_SECTIONS):
            if i > 0:
                root.addSpacing(12)
                root.addWidget(_divider())
                root.addSpacing(12)

            # Section header
            header = QLabel(section_title.upper())
            header.setStyleSheet(_SECTION_HEADER_QSS)
            root.addWidget(header)
            root.addSpacing(8)

            # Rows grid
            grid_widget = QWidget()
            grid = QGridLayout(grid_widget)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(8)
            grid.setColumnStretch(0, 1)

            for row_idx, (action, shortcut) in enumerate(rows):
                action_lbl = QLabel(action)
                action_lbl.setStyleSheet(_ACTION_QSS)

                shortcut_lbl = QLabel(shortcut)
                shortcut_lbl.setStyleSheet(_SHORTCUT_QSS)
                shortcut_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                shortcut_lbl.setFixedHeight(22)

                grid.addWidget(
                    action_lbl, row_idx, 0, Qt.AlignmentFlag.AlignVCenter
                )
                grid.addWidget(
                    shortcut_lbl,
                    row_idx,
                    1,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )

            root.addWidget(grid_widget)

        root.addStretch(1)

        # Close button — hides the window (same as pressing X)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 16, 0, 0)
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_CLOSE_BTN_QSS)
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def closeEvent(self, event: QEvent) -> None:
        """Hide instead of closing so the instance is preserved."""
        event.ignore()
        self.hide()
