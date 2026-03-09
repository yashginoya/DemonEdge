from __future__ import annotations

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from broker.broker_manager import BrokerManager
from feed.feed_models import SubscriptionMode
from models.position import Position
from models.tick import Tick
from utils.logger import get_logger
from widgets.base_widget import BaseWidget
from widgets.positions.pnl_summary import PnLSummary
from widgets.positions.positions_model import PositionsModel
from widgets.positions.trades_model import TradesModel

logger = get_logger(__name__)

_REFRESH_INTERVAL_MS = 30_000  # 30 seconds

_QSS = """
QTabWidget::pane {
    border: none;
    background: #0d1117;
}
QTabBar::tab {
    background: #161b22;
    color: #8b949e;
    padding: 4px 14px;
    height: 24px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 1px;
    font-size: 11px;
}
QTabBar::tab:selected {
    color: #e6edf3;
    border-bottom: 2px solid #1f6feb;
    background: #0d1117;
}
QTabBar::tab:hover:!selected {
    background: #1f2937;
    color: #e6edf3;
}
QTableView {
    background: #0d1117;
    alternate-background-color: #161b22;
    border: none;
    outline: none;
    color: #e6edf3;
    gridline-color: transparent;
    selection-background-color: #1f2937;
    selection-color: #e6edf3;
    font-size: 11px;
}
QHeaderView::section {
    background: #161b22;
    color: #8b949e;
    border: none;
    border-bottom: 1px solid #30363d;
    padding: 3px 6px;
    font-size: 10px;
}
QPushButton#refresh_btn {
    background: #21262d;
    color: #8b949e;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 2px 10px;
    font-size: 11px;
}
QPushButton#refresh_btn:hover {
    background: #30363d;
    color: #e6edf3;
}
"""


class _PositionsWorker(QThread):
    """Fetches positions + order book in background."""

    positions_ready = Signal(list)   # list[Position]
    orders_ready    = Signal(list)   # list[Order]
    failed          = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            broker = BrokerManager.get_broker()
            positions = broker.get_positions()
            self.positions_ready.emit(positions)
        except Exception as exc:
            logger.warning("PositionsWidget: get_positions failed: %s", exc)
            self.failed.emit(str(exc))

        try:
            broker = BrokerManager.get_broker()
            orders = broker.get_order_book()
            self.orders_ready.emit(orders)
        except Exception as exc:
            logger.warning("PositionsWidget: get_order_book failed: %s", exc)


class PositionsWidget(BaseWidget):
    """Positions & P&L widget.

    Shows open positions with live LTP / P&L updates (via MarketFeed), and a
    Trades tab with today's order book.  Refreshes positions from the broker
    every 30 seconds, and immediately after ``refresh()`` is called externally
    (e.g. after order placement by ``OrderEntryWidget``).
    """

    widget_id = "positions"

    # Signal bridge: feed thread → main thread
    _tick_signal = Signal(object)  # Tick

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Positions & P&L", parent)
        self.setMinimumHeight(120)

        root = QWidget()
        root.setStyleSheet(_QSS)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # P&L summary bar
        self._summary = PnLSummary()
        outer.addWidget(self._summary)

        # Tab widget
        self._tabs = QTabWidget()
        outer.addWidget(self._tabs, 1)

        # Positions tab
        self._pos_model = PositionsModel(self)
        self._pos_table = self._make_table(self._pos_model)
        self._tabs.addTab(self._pos_table, "Positions")

        # Trades tab
        self._trades_model = TradesModel(self)
        self._trades_table = self._make_table(self._trades_model)
        self._tabs.addTab(self._trades_table, "Trades")

        # Bottom row: refresh button
        bottom = QWidget()
        bottom.setStyleSheet("background:#161b22; border-top:1px solid #21262d;")
        bottom.setFixedHeight(28)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(4, 2, 4, 2)
        bottom_layout.addStretch()

        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.setObjectName("refresh_btn")
        self._refresh_btn.setFixedHeight(22)
        self._refresh_btn.clicked.connect(self.refresh)
        bottom_layout.addWidget(self._refresh_btn)
        outer.addWidget(bottom)

        self.setWidget(root)

        # Feed signal bridge
        self._tick_signal.connect(self._on_tick_ui)

        # 30-second auto-refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.refresh)

        self._worker: _PositionsWorker | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Trigger an immediate REST refresh of positions + order book."""
        if self._worker and self._worker.isRunning():
            return  # already refreshing
        self._start_worker()

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        self.refresh()
        self._refresh_timer.start()

    def on_hide(self) -> None:
        self._refresh_timer.stop()
        # feed unsubscription handled by BaseWidget._unsubscribe_all_feeds()

    def save_state(self) -> dict:
        return {}  # positions come from broker live

    def restore_state(self, state: dict) -> None:
        pass  # nothing to restore

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _start_worker(self) -> None:
        self._worker = _PositionsWorker(self)
        self._worker.positions_ready.connect(self._on_positions_ready)
        self._worker.orders_ready.connect(self._on_orders_ready)
        self._worker.start()

    def _on_positions_ready(self, positions: list[Position]) -> None:
        # Unsubscribe all previous feed subscriptions
        self._unsubscribe_all_feeds()

        # Update model
        self._pos_model.set_positions(positions)

        # Subscribe LTP for open positions
        for pos in positions:
            if pos.quantity != 0 and pos.token:
                self.subscribe_feed(
                    pos.exchange, pos.token,
                    self._tick_callback, SubscriptionMode.LTP
                )

        self._refresh_summary()

    def _on_orders_ready(self, orders) -> None:
        self._trades_model.set_orders(orders)

    # ------------------------------------------------------------------
    # Live feed
    # ------------------------------------------------------------------

    def _tick_callback(self, tick: Tick) -> None:
        """Feed thread — emit to cross to main thread."""
        self._tick_signal.emit(tick)

    def _on_tick_ui(self, tick: Tick) -> None:
        """Main thread — update model."""
        self._pos_model.update_ltp(tick.token, tick.ltp)
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Summary update
    # ------------------------------------------------------------------

    def _refresh_summary(self) -> None:
        real, unreal, total = self._pos_model.get_totals()
        count = self._pos_model.position_count()
        self._summary.update(real, unreal, total, count)

    # ------------------------------------------------------------------
    # Table factory
    # ------------------------------------------------------------------

    @staticmethod
    def _make_table(model) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(24)
        h = table.horizontalHeader()
        h.setStretchLastSection(False)
        # Symbol column stretches, rest resize to contents
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, model.COLUMN_COUNT):
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        return table


# Self-register at import time
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=PositionsWidget.widget_id,
        display_name="Positions & P&L",
        category="Orders",
        factory=PositionsWidget,
    )
)
