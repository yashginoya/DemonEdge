from __future__ import annotations

from PySide6.QtCore import QModelIndex, QObject, QRunnable, QThreadPool, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from feed.feed_models import SubscriptionMode
from feed.feed_manager import FeedManager
from models.instrument import Instrument
from models.tick import Tick
from widgets.watchlist.watchlist_model import WatchlistModel

from utils.logger import get_logger

logger = get_logger(__name__)


class _QuoteFetchWorker(QRunnable):
    """Fetches snapshot quote (LTP + prev_close) for a token off the main thread."""

    class _Signals(QObject):
        done = Signal(str, float, float)   # token, ltp, prev_close
        failed = Signal(str)               # token

    def __init__(self, exchange: str, token: str) -> None:
        super().__init__()
        self.signals = _QuoteFetchWorker._Signals()
        self._exchange = exchange
        self._token = token

    def run(self) -> None:
        try:
            from broker.broker_manager import BrokerManager
            quote = BrokerManager.get_broker().get_quote(self._exchange, self._token)
            self.signals.done.emit(self._token, quote["ltp"], quote["prev_close"])
        except Exception as exc:
            logger.debug("Quote fetch failed for %s:%s — %s", self._exchange, self._token, exc)
            self.signals.failed.emit(self._token)


class WatchlistTab(QWidget):
    """Single watchlist tab — independent list of instruments with live LTP.

    Manages its own MarketFeed subscriptions.  Call ``subscribe_all()`` /
    ``unsubscribe_all()`` when the parent widget is shown / hidden.
    """

    # Emitted from feed thread; connected to _on_tick_ui (main thread)
    tick_arrived = Signal(object)  # Tick

    # Emitted when user double-clicks a row — carries the Instrument
    instrument_selected = Signal(object)  # Instrument

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._model = WatchlistModel(self)
        self._subscribed: set[str] = set()   # tokens currently subscribed

        self._build_ui()

        # Connect tick signal bridge
        self.tick_arrived.connect(self._on_tick_ui)

        # Flash animation — 100ms steps
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._flash_step)
        self._flash_timer.start(100)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        # Toolbar row
        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(6, 0, 6, 0)
        tb_layout.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search symbol…")
        self._search_input.setFixedHeight(26)
        self._search_input.returnPressed.connect(self._open_search_dialog)

        self._search_btn = QPushButton("Search")
        self._search_btn.setFixedHeight(26)
        self._search_btn.clicked.connect(self._open_search_dialog)

        self._add_manual_btn = QPushButton("+ Manual")
        self._add_manual_btn.setFixedHeight(26)
        self._add_manual_btn.clicked.connect(self._open_manual_dialog)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setFixedHeight(26)
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._remove_selected)

        tb_layout.addWidget(self._search_input, 1)
        tb_layout.addWidget(self._search_btn)
        tb_layout.addWidget(self._add_manual_btn)
        tb_layout.addWidget(self._remove_btn)

        # Table
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_row_context_menu)

        h = self._table.horizontalHeader()
        h.setSectionResizeMode(WatchlistModel.COL_SYMBOL, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(WatchlistModel.COL_EXCHANGE, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(WatchlistModel.COL_LTP, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(WatchlistModel.COL_CHANGE, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(WatchlistModel.COL_CHANGE_PCT, QHeaderView.ResizeMode.ResizeToContents)

        # Enable Remove button when a row is selected
        self._table.selectionModel().selectionChanged.connect(
            lambda sel, _: self._remove_btn.setEnabled(len(sel.indexes()) > 0)
        )

        # Double-click → emit instrument_selected
        self._table.doubleClicked.connect(self._on_row_double_clicked)

        # Table must receive keyboard focus so key events reach the monkey-patch
        self._table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Delete / F5 key handling (overrides table default keyPressEvent)
        self._table.keyPressEvent = self._table_key_press

        # Status message (brief feedback)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "color: #8b949e; font-size: 11px; padding: 2px 6px;"
        )
        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.timeout.connect(lambda: self._status_label.setText(""))

        layout.addWidget(toolbar)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status_label)

    # ------------------------------------------------------------------
    # Instrument add / remove
    # ------------------------------------------------------------------

    def _open_search_dialog(self) -> None:
        from widgets.watchlist.search_dialog import SearchDialog
        dlg = SearchDialog(self)
        # Pre-fill search if user typed something
        typed = self._search_input.text().strip()
        if typed:
            dlg._search_input.setText(typed)
            dlg._on_text_changed(typed)
        dlg.instrument_selected.connect(self._add_instrument)
        dlg.exec()
        self._search_input.clear()

    def _open_manual_dialog(self) -> None:
        from widgets.watchlist.add_manual_dialog import AddManualDialog
        dlg = AddManualDialog(self)
        dlg.instrument_selected.connect(self._add_instrument)
        dlg.exec()

    def _add_instrument(self, instrument: Instrument) -> None:
        """Add instrument to model, subscribe to feed, fetch initial LTP."""
        added = self._model.add_instrument(instrument)
        if not added:
            self._show_status("Already in watchlist")
            return

        # Subscribe to live feed
        key = instrument.token
        if key not in self._subscribed:
            FeedManager.get_feed().subscribe(
                instrument.exchange, instrument.token,
                self._tick_callback, SubscriptionMode.LTP
            )
            self._subscribed.add(key)

        # Fetch snapshot quote (LTP + prev_close) in background
        worker = _QuoteFetchWorker(instrument.exchange, instrument.token)
        worker.signals.done.connect(self._on_initial_ltp)
        QThreadPool.globalInstance().start(worker)

    def _remove_selected(self) -> None:
        indexes = self._table.selectedIndexes()
        if not indexes:
            return
        row_index = indexes[0].row()
        self._remove_row(row_index)

    def _remove_row(self, row_index: int) -> None:
        instrument = self._model.remove_instrument(row_index)
        token = instrument.token
        if token in self._subscribed:
            FeedManager.get_feed().unsubscribe(
                instrument.exchange, token, self._tick_callback
            )
            self._subscribed.discard(token)

    # ------------------------------------------------------------------
    # Tick handling
    # ------------------------------------------------------------------

    def _tick_callback(self, tick: Tick) -> None:
        """Called on feed thread — emit to cross to main thread."""
        self.tick_arrived.emit(tick)

    def _on_tick_ui(self, tick: Tick) -> None:
        """Runs on Qt main thread — update model."""
        self._model.update_tick(tick.token, tick)

    def _on_initial_ltp(self, token: str, ltp: float, prev_close: float) -> None:
        """REST quote fetch result — populate LTP and prev_close from snapshot."""
        self._model.update_initial_ltp(token, ltp, prev_close)

    # ------------------------------------------------------------------
    # Flash animation
    # ------------------------------------------------------------------

    def _flash_step(self) -> None:
        changed = self._model.tick_flash_step()
        for i in changed:
            tl = self._model.index(i, 0)
            br = self._model.index(i, self._model.COLUMN_COUNT - 1)
            self._model.dataChanged.emit(tl, br, [Qt.ItemDataRole.BackgroundRole])

    # ------------------------------------------------------------------
    # Context menu on table rows
    # ------------------------------------------------------------------

    def _show_row_context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        row_index = index.row()
        row = self._model.get_row(row_index)
        inst = row.instrument

        menu = QMenu(self)

        copy_symbol_action = QAction(f"Copy Symbol  ({inst.symbol})", self)
        copy_symbol_action.triggered.connect(
            lambda: QApplication.clipboard().setText(inst.symbol)
        )
        menu.addAction(copy_symbol_action)

        copy_token_action = QAction(f"Copy Token  ({inst.token})", self)
        copy_token_action.triggered.connect(
            lambda: QApplication.clipboard().setText(inst.token)
        )
        menu.addAction(copy_token_action)

        menu.addSeparator()

        remove_action = QAction("Remove from Watchlist", self)
        remove_action.triggered.connect(lambda: self._remove_row(row_index))
        menu.addAction(remove_action)

        menu.addSeparator()

        chart_action = QAction("Add to Chart", self)
        chart_action.triggered.connect(lambda: self._add_to_chart(inst))
        menu.addAction(chart_action)

        menu.addSeparator()

        md_action = QAction("Market Depth  \tF5", self)
        md_action.triggered.connect(lambda: self._open_market_depth_for(inst))
        menu.addAction(md_action)

        menu.addSeparator()

        buy_action = QAction("Buy", self)
        buy_action.triggered.connect(lambda: self._order_entry_with_side(inst, "BUY"))
        menu.addAction(buy_action)

        sell_action = QAction("Sell", self)
        sell_action.triggered.connect(lambda: self._order_entry_with_side(inst, "SELL"))
        menu.addAction(sell_action)

        menu.addSeparator()

        oc_action = QAction("Option Chain", self)
        oc_action.triggered.connect(lambda: self._open_option_chain_for(inst))
        menu.addAction(oc_action)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def _add_to_chart(self, instrument: Instrument) -> None:
        """Send instrument to the first active ChartWidget."""
        from PySide6.QtWidgets import QApplication
        main_window = QApplication.activeWindow()
        if main_window is None:
            return
        get_fn = getattr(main_window, 'get_first_widget_of_type', None)
        if get_fn is None:
            return
        chart = get_fn("chart")
        if chart is not None:
            chart._load_chart(instrument, chart._timeframe)
        else:
            logger.debug("No chart widget open to receive instrument")

    def _open_market_depth_for_selected(self) -> None:
        """F5 handler — open Market Depth for the currently selected row."""
        indexes = self._table.selectedIndexes()
        if not indexes:
            return
        row = self._model.get_row(indexes[0].row())
        self._open_market_depth_for(row.instrument)

    def _open_market_depth_for(self, instrument: Instrument) -> None:
        from PySide6.QtWidgets import QApplication
        mw = QApplication.activeWindow()
        fn = getattr(mw, "open_market_depth_for_instrument", None)
        if fn:
            fn(instrument)

    def _order_entry_with_side(self, instrument: Instrument, side: str) -> None:
        from PySide6.QtWidgets import QApplication
        mw = QApplication.activeWindow()
        fn = getattr(mw, "send_instrument_to_order_entry_with_side", None)
        if fn:
            fn(instrument, side)

    def _open_option_chain_for(self, instrument: Instrument) -> None:
        from PySide6.QtWidgets import QApplication
        mw = QApplication.activeWindow()
        fn = getattr(mw, "open_option_chain_for_symbol", None)
        if fn:
            fn(instrument.symbol)

    def _on_row_double_clicked(self, index: QModelIndex) -> None:
        """Emit instrument_selected when the user double-clicks a row."""
        row = self._model.get_row(index.row())
        self.instrument_selected.emit(row.instrument)

    def _table_key_press(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self._remove_selected()
        elif event.key() == Qt.Key.Key_F5:
            indexes = self._table.selectedIndexes()
            if indexes:
                row = self._model.get_row(indexes[0].row())
                self._open_market_depth_for(row.instrument)
                # Consume the event — prevents propagation to MainWindow's F5 handler
            else:
                QTableView.keyPressEvent(self._table, event)
        else:
            QTableView.keyPressEvent(self._table, event)

    # ------------------------------------------------------------------
    # Subscription management (called by WatchlistWidget on show/hide)
    # ------------------------------------------------------------------

    def subscribe_all(self) -> None:
        """Re-subscribe all instruments (call when parent widget is shown)."""
        for inst in self._model.get_all_instruments():
            key = inst.token
            if key not in self._subscribed:
                FeedManager.get_feed().subscribe(
                    inst.exchange, inst.token,
                    self._tick_callback, SubscriptionMode.LTP
                )
                self._subscribed.add(key)

    def unsubscribe_all(self) -> None:
        """Unsubscribe all instruments (call when parent widget is hidden)."""
        for inst in self._model.get_all_instruments():
            FeedManager.get_feed().unsubscribe(
                inst.exchange, inst.token, self._tick_callback
            )
        self._subscribed.clear()

    # ------------------------------------------------------------------
    # Status bar helper
    # ------------------------------------------------------------------

    def _show_status(self, msg: str, duration_ms: int = 2000) -> None:
        self._status_label.setText(msg)
        self._status_clear_timer.start(duration_ms)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self) -> dict:
        return {
            "instruments": [
                {
                    "symbol": inst.symbol,
                    "token": inst.token,
                    "exchange": inst.exchange,
                    "name": inst.name,
                    "instrument_type": inst.instrument_type,
                }
                for inst in self._model.get_all_instruments()
            ]
        }

    def restore_state(self, state: dict) -> None:
        for item in state.get("instruments", []):
            try:
                instrument = Instrument(**item)
                self._add_instrument(instrument)
            except Exception as exc:
                logger.warning("Failed to restore instrument %s: %s", item, exc)
