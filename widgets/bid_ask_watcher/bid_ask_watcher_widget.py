"""Bid/Ask Quantity Watcher widget.

Watches, per underlying, the total bid quantity and total ask quantity summed
across N near-the-money option strikes on the call side (ATM→OTM up) and the put
side (ATM→OTM down).  Add underlyings like a watchlist; configure the strike
count and expiry per row.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from utils.logger import get_logger
from widgets.base_widget import BaseWidget
from widgets.bid_ask_watcher.add_ticker_dialog import AddTickerDialog
from widgets.bid_ask_watcher.bid_ask_model import BidAskModel
from widgets.bid_ask_watcher.ticker_watch import TickerWatch

logger = get_logger(__name__)

_QSS = """
QWidget#content { background: #0d1117; }
QTableView {
    background: #0d1117; alternate-background-color: #0d1117;
    border: none; outline: none; color: #e6edf3;
    gridline-color: transparent; selection-background-color: #1f2937;
    selection-color: #e6edf3;
}
QHeaderView::section {
    background: #161b22; color: #8b949e; border: none;
    border-bottom: 1px solid #30363d; padding: 4px 6px; font-size: 11px;
}
QPushButton {
    background: #21262d; color: #e6edf3; border: 1px solid #30363d;
    border-radius: 3px; padding: 3px 10px;
}
QPushButton:hover { background: #30363d; }
QMenu { background: #161b22; border: 1px solid #30363d; color: #e6edf3; }
QMenu::item:selected { background: #1f6feb; color: #ffffff; }
"""


class BidAskWatcherWidget(BaseWidget):
    """Total bid/ask quantity across near-the-money strikes, per underlying."""

    widget_id = "bid_ask_watcher"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Bid/Ask Watcher", parent)
        self.setMinimumWidth(420)

        self._model = BidAskModel(self)
        self._shown = False
        self._dirty_rows: set[int] = set()

        self._build_ui()

        # Coalesce high-frequency tick updates into ~10 Hz repaints.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._flush_dirty)
        self._refresh_timer.start(100)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        content = QWidget()
        content.setObjectName("content")
        content.setStyleSheet(_QSS)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        toolbar = QWidget()
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(6, 0, 6, 0)
        tb.setSpacing(4)
        self._add_btn = QPushButton("+ Add Symbol")
        self._add_btn.clicked.connect(self._open_add_dialog)
        tb.addWidget(self._add_btn)
        tb.addStretch(1)

        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.doubleClicked.connect(lambda _i: self._configure_selected())
        self._table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._table.keyPressEvent = self._table_key_press

        h = self._table.horizontalHeader()
        h.setSectionResizeMode(BidAskModel.COL_SYMBOL, QHeaderView.ResizeMode.Stretch)
        for col in range(1, BidAskModel.COLUMN_COUNT):
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(toolbar)
        layout.addWidget(self._table, 1)
        self.setWidget(content)

    # ------------------------------------------------------------------
    # Add / configure / remove
    # ------------------------------------------------------------------

    def _open_add_dialog(self) -> None:
        dlg = AddTickerDialog(self)
        dlg.config_selected.connect(self._add_ticker)
        dlg.exec()

    def _add_ticker(self, underlying: str, expiry: str, num_strikes: int) -> None:
        ticker = TickerWatch(underlying, expiry, num_strikes, parent=self)
        ticker.changed.connect(lambda t=ticker: self._mark_dirty(t))
        ticker.status_changed.connect(lambda t=ticker: self._mark_dirty(t))
        self._model.add_ticker(ticker)
        if self._shown:
            ticker.start()

    def _configure_selected(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        ticker = self._model.get_ticker(row)
        if ticker is None:
            return
        dlg = AddTickerDialog(
            self,
            underlying=ticker.underlying,
            expiry=ticker.expiry,
            num_strikes=ticker.num_strikes,
            edit=True,
        )
        dlg.config_selected.connect(
            lambda u, e, n, t=ticker: self._apply_config(t, e, n)
        )
        dlg.exec()

    def _apply_config(self, ticker: TickerWatch, expiry: str, num_strikes: int) -> None:
        if num_strikes != ticker.num_strikes:
            ticker.set_num_strikes(num_strikes)
        if expiry != ticker.expiry:
            ticker.set_expiry(expiry)
        self._mark_dirty(ticker)

    def _remove_selected(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        ticker = self._model.remove_row(row)
        if ticker is not None:
            ticker.stop()
            ticker.deleteLater()

    # ------------------------------------------------------------------
    # Tick refresh coalescing
    # ------------------------------------------------------------------

    def _mark_dirty(self, ticker: TickerWatch) -> None:
        row = self._model.row_of(ticker)
        if row >= 0:
            self._dirty_rows.add(row)

    def _flush_dirty(self) -> None:
        if not self._dirty_rows:
            return
        for row in self._dirty_rows:
            self._model.refresh_row(row)
        self._dirty_rows.clear()

    # ------------------------------------------------------------------
    # Context menu / keys
    # ------------------------------------------------------------------

    def _selected_row(self) -> int:
        idx = self._table.selectedIndexes()
        return idx[0].row() if idx else -1

    def _show_context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self)
        cfg = QAction("Configure…", self)
        cfg.triggered.connect(self._configure_selected)
        menu.addAction(cfg)
        menu.addSeparator()
        rm = QAction("Remove", self)
        rm.triggered.connect(self._remove_selected)
        menu.addAction(rm)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _table_key_press(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self._remove_selected()
        else:
            QTableView.keyPressEvent(self._table, event)

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        self._shown = True
        for ticker in self._model.all_tickers():
            ticker.start()

    def on_hide(self) -> None:
        self._shown = False
        for ticker in self._model.all_tickers():
            ticker.stop()

    def save_state(self) -> dict:
        return {"tickers": [t.config_dict() for t in self._model.all_tickers()]}

    def restore_state(self, state: dict) -> None:
        for cfg in state.get("tickers", []):
            try:
                self._add_ticker(
                    cfg.get("underlying", ""),
                    cfg.get("expiry", ""),
                    int(cfg.get("num_strikes", 5)),
                )
            except Exception as exc:
                logger.warning("Failed to restore bid/ask ticker %s: %s", cfg, exc)


# Self-register at import time
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=BidAskWatcherWidget.widget_id,
        display_name="Bid/Ask Watcher",
        category="Market Data",
        factory=BidAskWatcherWidget,
        description="Total bid/ask quantity across ATM→OTM option strikes per underlying",
    )
)
