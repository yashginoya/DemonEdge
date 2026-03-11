"""LogViewerWindow — standalone real-time log panel with 4 categorised tabs.

Tabs
----
System      broker connection, startup/shutdown, everything not caught elsewhere
Orders      broker order calls, widgets.order*, and order-related broker logs
Market Data feed.* and market* loggers
Errors      all ERROR and CRITICAL records from every logger (aggregated)

Toolbar (shared, acts on current tab)
--------------------------------------
Level filter | Search | Auto-scroll | Clear | Export
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QFont, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from utils.logger import get_logger
from widgets.log_viewer.qt_log_handler import QtLogHandler

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_MAX_ROWS = 2000

_LEVEL_FILTER_OPTIONS: list[tuple[str, int]] = [
    ("ALL",      logging.DEBUG),
    ("INFO+",    logging.INFO),
    ("WARNING+", logging.WARNING),
    ("ERROR+",   logging.ERROR),
]

_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG:    "#6e7681",   # grey
    logging.INFO:     "#e6edf3",   # light / white
    logging.WARNING:  "#d29922",   # amber
    logging.ERROR:    "#f85149",   # red
    logging.CRITICAL: "#ff4444",   # bright red
}

_TAB_SYSTEM = 0
_TAB_ORDERS = 1
_TAB_MARKET = 2
_TAB_ERRORS = 3

_TAB_NAMES = ["System", "Orders", "Market Data", "Errors"]
_COLUMNS   = ["Time", "Level", "Source", "Message"]
_COL_WIDTHS = [75, 65, 160, -1]   # -1 = stretch last column

# ── Routing ────────────────────────────────────────────────────────────────────

_ORDER_KEYWORDS = ("order", "place", "cancel", "modif", "margin", "trade")


def _is_order_related(record: logging.LogRecord) -> bool:
    name_l = record.name.lower()
    try:
        msg_l = record.getMessage().lower()
    except Exception:  # noqa: BLE001
        msg_l = ""
    return any(k in name_l for k in _ORDER_KEYWORDS) or any(
        k in msg_l for k in _ORDER_KEYWORDS
    )


def _route_record(record: logging.LogRecord) -> list[int]:
    """Return list of tab indices this record belongs to."""
    tabs: list[int] = []
    name = record.name.lower()

    if name.startswith("feed.") or name.startswith("market"):
        tabs.append(_TAB_MARKET)
    elif name.startswith("widgets.order"):
        tabs.append(_TAB_ORDERS)
    elif name.startswith("broker."):
        tabs.append(_TAB_ORDERS if _is_order_related(record) else _TAB_SYSTEM)
    else:
        tabs.append(_TAB_SYSTEM)

    # Errors aggregation: ERROR/CRITICAL from any logger also goes to Errors tab
    if record.levelno >= logging.ERROR and _TAB_ERRORS not in tabs:
        tabs.append(_TAB_ERRORS)

    return tabs


# ── Single log tab ─────────────────────────────────────────────────────────────

_TABLE_QSS = """
QTableWidget {
    background: #0d1117;
    alternate-background-color: #161b22;
    color: #e6edf3;
    border: none;
    gridline-color: #21262d;
}
QHeaderView::section {
    background: #161b22;
    color: #8b949e;
    border: none;
    border-right: 1px solid #21262d;
    padding: 3px 6px;
    font-size: 11px;
}
QScrollBar:vertical {
    background: #0d1117;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #0d1117;
    height: 8px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


class _LogTab(QWidget):
    """Scrollable log table for one category."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(18)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setWordWrap(False)
        self._table.setFont(QFont("Consolas", 8))
        self._table.setStyleSheet(_TABLE_QSS)

        for i, w in enumerate(_COL_WIDTHS):
            if w > 0:
                self._table.setColumnWidth(i, w)

        layout.addWidget(self._table)

        self._auto_scroll = True

    # ------------------------------------------------------------------
    # Public API called by LogViewerWidget
    # ------------------------------------------------------------------

    def add_record(
        self,
        record: logging.LogRecord,
        level_filter: int,
        search_text: str,   # already lowercased
    ) -> None:
        """Append a record, enforcing the row cap."""
        # Drop oldest rows when at cap
        while self._table.rowCount() >= _MAX_ROWS:
            self._table.removeRow(0)

        row = self._table.rowCount()
        self._table.insertRow(row)

        time_str   = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level_str  = record.levelname
        source_str = record.name
        try:
            msg_str = record.getMessage()
        except Exception:  # noqa: BLE001
            msg_str = str(record.msg)

        color = QColor(_LEVEL_COLORS.get(record.levelno, _LEVEL_COLORS[logging.INFO]))
        is_critical = record.levelno >= logging.CRITICAL
        font = QFont("Consolas", 8)
        font.setBold(is_critical)

        for col, text in enumerate([time_str, level_str, source_str, msg_str]):
            item = QTableWidgetItem(text)
            item.setForeground(color)
            item.setFont(font)
            # Store level number on every cell so apply_filter can retrieve it
            item.setData(Qt.ItemDataRole.UserRole, record.levelno)
            self._table.setItem(row, col, item)

        hidden = self._should_hide(record.levelno, msg_str, source_str, level_filter, search_text)
        self._table.setRowHidden(row, hidden)

        if self._auto_scroll and not hidden:
            self._table.scrollToBottom()

    def apply_filter(self, level_filter: int, search_text: str) -> None:
        """Re-evaluate visibility for all rows. search_text must be lowercased."""
        for row in range(self._table.rowCount()):
            level_item  = self._table.item(row, 1)
            msg_item    = self._table.item(row, 3)
            source_item = self._table.item(row, 2)
            if level_item is None:
                continue
            level_no   = level_item.data(Qt.ItemDataRole.UserRole) or logging.DEBUG
            msg_text   = msg_item.text()   if msg_item    else ""
            src_text   = source_item.text() if source_item else ""
            hidden = self._should_hide(level_no, msg_text, src_text, level_filter, search_text)
            self._table.setRowHidden(row, hidden)

        if self._auto_scroll:
            self._table.scrollToBottom()

    def clear_rows(self) -> None:
        self._table.setRowCount(0)

    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled
        if enabled:
            self._table.scrollToBottom()

    def export_to_csv(self, filepath: str) -> int:
        """Write visible rows to CSV. Returns exported row count."""
        count = 0
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(_COLUMNS)
            for row in range(self._table.rowCount()):
                if not self._table.isRowHidden(row):
                    row_data = [
                        self._table.item(row, col).text()
                        if self._table.item(row, col) else ""
                        for col in range(len(_COLUMNS))
                    ]
                    writer.writerow(row_data)
                    count += 1
        return count

    # ------------------------------------------------------------------

    @staticmethod
    def _should_hide(
        level_no: int,
        msg: str,
        source: str,
        level_filter: int,
        search_lower: str,
    ) -> bool:
        if level_no < level_filter:
            return True
        if search_lower and (
            search_lower not in msg.lower() and search_lower not in source.lower()
        ):
            return True
        return False


# ── Main widget ────────────────────────────────────────────────────────────────

_TOOLBAR_QSS = """
QWidget#LogToolbar {
    background: #161b22;
    border-bottom: 1px solid #30363d;
}
QLabel {
    color: #8b949e;
    font-size: 11px;
}
QComboBox {
    background: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 11px;
    min-width: 82px;
}
QComboBox::drop-down { border: none; width: 16px; }
QComboBox QAbstractItemView {
    background: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    selection-background-color: #30363d;
}
QLineEdit {
    background: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 11px;
}
QPushButton {
    background: #21262d;
    color: #8b949e;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 2px 9px;
    font-size: 11px;
}
QPushButton:hover { background: #30363d; color: #e6edf3; }
QPushButton#autoScrollBtn[active="true"] {
    color: #3fb950;
    border-color: #3fb950;
}
"""


class LogViewerWindow(QWidget):
    """Standalone log viewer window with 4 categorised tabs, live filtering, and export.

    Opened/closed from the main window status bar.  Hiding via the window's
    own close button (X) only hides it — the instance persists so logs keep
    accumulating.  The main window explicitly hides it on app exit.
    """

    # Emitted when the window is shown or hidden so the status-bar button
    # can update its visual state.
    visibility_changed = Signal(bool)   # True = became visible, False = hidden

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("DemonEdge - Log Viewer")
        self.resize(1000, 600)

        # Filter state — initialised before buffer replay
        self._level_filter: int = logging.DEBUG
        self._search_text:  str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setObjectName("LogToolbar")
        toolbar.setStyleSheet(_TOOLBAR_QSS)
        toolbar.setFixedHeight(34)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 3, 8, 3)
        tb.setSpacing(6)

        tb.addWidget(QLabel("Level:"))

        self._level_combo = QComboBox()
        for label, _ in _LEVEL_FILTER_OPTIONS:
            self._level_combo.addItem(label)
        self._level_combo.currentIndexChanged.connect(self._on_filter_changed)
        tb.addWidget(self._level_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedWidth(200)
        self._search_edit.textChanged.connect(self._on_filter_changed)
        tb.addWidget(self._search_edit)

        tb.addStretch()

        self._autoscroll_btn = QPushButton("⬇ Auto-scroll")
        self._autoscroll_btn.setObjectName("autoScrollBtn")
        self._autoscroll_btn.setCheckable(True)
        self._autoscroll_btn.setChecked(True)
        self._autoscroll_btn.setProperty("active", "true")
        self._autoscroll_btn.toggled.connect(self._on_autoscroll_toggled)
        tb.addWidget(self._autoscroll_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear)
        tb.addWidget(clear_btn)

        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._on_export)
        tb.addWidget(export_btn)

        root.addWidget(toolbar)

        # ── Tab widget ─────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background: #161b22;
                color: #8b949e;
                padding: 5px 16px;
                border: none;
                border-right: 1px solid #21262d;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: #0d1117;
                color: #e6edf3;
                border-bottom: 2px solid #1f6feb;
            }
            QTabBar::tab:hover { color: #e6edf3; }
        """)

        self._log_tabs: list[_LogTab] = []
        for name in _TAB_NAMES:
            tab = _LogTab()
            self._log_tabs.append(tab)
            self._tabs.addTab(tab, name)

        root.addWidget(self._tabs)

        # ── Connect to QtLogHandler and replay buffer ──────────────────
        handler = QtLogHandler.instance()
        handler.record_emitted.connect(self._on_record)
        for record in handler.buffer:
            self._dispatch_record(record)

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Hide instead of destroying — logs keep accumulating while hidden."""
        event.ignore()
        self.hide()
        self.visibility_changed.emit(False)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.visibility_changed.emit(True)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    @Slot(object)
    def _on_record(self, record: logging.LogRecord) -> None:
        self._dispatch_record(record)

    def _dispatch_record(self, record: logging.LogRecord) -> None:
        for idx in _route_record(record):
            self._log_tabs[idx].add_record(record, self._level_filter, self._search_text)

    def _on_filter_changed(self) -> None:
        idx = self._level_combo.currentIndex()
        self._level_filter = _LEVEL_FILTER_OPTIONS[idx][1]
        self._search_text  = self._search_edit.text().lower()
        for tab in self._log_tabs:
            tab.apply_filter(self._level_filter, self._search_text)

    def _on_autoscroll_toggled(self, checked: bool) -> None:
        self._autoscroll_btn.setProperty("active", "true" if checked else "false")
        self._autoscroll_btn.style().unpolish(self._autoscroll_btn)
        self._autoscroll_btn.style().polish(self._autoscroll_btn)
        for tab in self._log_tabs:
            tab.set_auto_scroll(checked)

    def _on_clear(self) -> None:
        current = self._tabs.currentIndex()
        if 0 <= current < len(self._log_tabs):
            self._log_tabs[current].clear_rows()

    def _on_export(self) -> None:
        current = self._tabs.currentIndex()
        if not (0 <= current < len(self._log_tabs)):
            return
        tab_name     = _TAB_NAMES[current].lower().replace(" ", "_")
        timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"logs_{tab_name}_{timestamp}.csv"
        filepath, _  = QFileDialog.getSaveFileName(
            self,
            "Export Logs",
            str(Path.home() / default_name),
            "CSV Files (*.csv);;All Files (*)",
        )
        if filepath:
            count = self._log_tabs[current].export_to_csv(filepath)
            logger.info("Exported %d log rows to %s", count, filepath)
