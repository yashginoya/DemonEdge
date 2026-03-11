"""OptionChainWidget — live option chain viewer for any index or stock."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Callable

from PySide6.QtCore import QModelIndex, QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from feed.feed_models import SubscriptionMode
from models.tick import Tick
from utils.logger import get_logger
from widgets.base_widget import BaseWidget
from widgets.option_chain import option_chain_builder as builder
from widgets.option_chain.column_selector_dialog import ColumnSelectorDialog
from widgets.option_chain.iv_calculator import calculate_delta, calculate_iv
from widgets.option_chain.option_chain_model import ALL_COLUMNS, OptionChainHeaderView, OptionChainModel
from widgets.option_chain.option_chain_row import OptionChainRow

logger = get_logger(__name__)

# Hardcoded index token map for common NSE/BSE indices
INDEX_TOKENS: dict[str, dict[str, str]] = {
    "NIFTY":      {"token": "26000", "exchange": "NSE"},
    "BANKNIFTY":  {"token": "26009", "exchange": "NSE"},
    "FINNIFTY":   {"token": "26037", "exchange": "NSE"},
    "MIDCPNIFTY": {"token": "26074", "exchange": "NSE"},
    "SENSEX":     {"token": "1",     "exchange": "BSE"},
}

# Max tokens to subscribe — warn above this; restrict to ±N strikes if exceeded
_SUBSCRIPTION_LIMIT = 950
_STRIKE_WINDOW       = 50  # subscribe only ±50 strikes of ATM when over limit

# Default strikes shown/subscribed on each side of ATM
_DEFAULT_STRIKES_PER_SIDE = 20

_QSS = """
QWidget {
    background: #0d1117;
    color: #e6edf3;
    font-size: 12px;
}
QTableView {
    background: #0d1117;
    alternate-background-color: #161b22;
    border: none;
    outline: none;
    color: #e6edf3;
    gridline-color: #1f2937;
    selection-background-color: #1f2937;
    selection-color: #e6edf3;
}
QHeaderView::section {
    background: #161b22;
    color: #8b949e;
    border: none;
    border-right: 1px solid #30363d;
    padding: 2px 4px;
    font-size: 11px;
}
QLineEdit {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 3px;
    color: #e6edf3;
    padding: 2px 6px;
}
QLineEdit:focus {
    border-color: #1f6feb;
}
QComboBox {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 3px;
    color: #e6edf3;
    padding: 2px 6px;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background: #161b22;
    border: 1px solid #30363d;
    color: #e6edf3;
    selection-background-color: #1f6feb;
}
QPushButton {
    background: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 3px 10px;
}
QPushButton:hover {
    background: #30363d;
}
QFrame#ltpBar {
    background: #161b22;
    border-bottom: 1px solid #30363d;
}
"""


# ── Strikes settings dialog ───────────────────────────────────────────────────

class _StrikesSettingsDialog(QDialog):
    """Small dialog for configuring how many strikes are shown per side of ATM."""

    def __init__(self, symbol: str, current_n: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Strike Settings")
        self.setFixedSize(260, 100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)

        if symbol:
            sym_lbl = QLabel(f"<b>{symbol}</b>")
            form.addRow("Symbol:", sym_lbl)

        self._spinbox = QSpinBox()
        self._spinbox.setRange(5, 50)
        self._spinbox.setSingleStep(5)
        self._spinbox.setValue(current_n)
        # No suffix — clean number-only display
        self._spinbox.setToolTip(
            "Number of strikes shown on each side of ATM.\n"
            "Total visible = 2 × N + 1 (the ATM strike itself)."
        )
        self._spinbox.setFixedWidth(60)
        self._spinbox.setFixedHeight(24)
        self._spinbox.setStyleSheet("""
            QSpinBox {
                background: #161b22;
                color: #e6edf3;
                border: 1px solid #30363d;
                border-radius: 3px;
                padding: 1px 6px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0;
                border: none;
            }
        """)
        form.addRow("Strikes per side:", self._spinbox)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        for btn in buttons.buttons():
            btn.setFixedSize(80, 28)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> int:
        return self._spinbox.value()


# ── Worker ────────────────────────────────────────────────────────────────────

class _ChainLoadSignals(QObject):
    finished = Signal(list, float, list, str, str)  # rows, underlying_ltp, expiries, expiry, underlying_token_exchange
    failed   = Signal(str)


class _ChainLoadWorker(QRunnable):
    """Loads expiries, builds chain, fetches underlying LTP — off the main thread."""

    def __init__(
        self,
        underlying_name: str,
        expiry: str,           # empty string → use nearest expiry
        exchange: str = "NFO",
    ) -> None:
        super().__init__()
        self.signals = _ChainLoadSignals()
        self._underlying = underlying_name.upper().strip()
        self._expiry = expiry
        self._exchange = exchange

    def run(self) -> None:
        try:
            expiries = builder.get_expiries(self._underlying, self._exchange)
            if not expiries:
                self.signals.failed.emit(f"No options found for '{self._underlying}'")
                return

            expiry = self._expiry if self._expiry in expiries else expiries[0]
            rows   = builder.build_chain(self._underlying, expiry, self._exchange)

            # Fetch underlying LTP
            ltp = 0.0
            try:
                from broker.broker_manager import BrokerManager
                info = INDEX_TOKENS.get(self._underlying)
                if info:
                    ltp = BrokerManager.get_broker().get_ltp(info["exchange"], info["token"])
                else:
                    # Stock — search for EQ token
                    from broker.instrument_master import InstrumentMaster
                    eq_key = f"NSE:{self._underlying}-EQ"
                    # Try direct token lookup or search
                    results = InstrumentMaster.search(f"{self._underlying}-EQ", exchange="NSE", max_results=5)
                    if results:
                        ltp = BrokerManager.get_broker().get_ltp(results[0].exchange, results[0].token)
            except Exception as exc:
                logger.warning("Could not fetch underlying LTP: %s", exc)

            # Underlying exchange for feed subscription
            idx_info = INDEX_TOKENS.get(self._underlying, {})
            underlying_exch = idx_info.get("exchange", "NSE")

            self.signals.finished.emit(rows, ltp, expiries, expiry, underlying_exch)

        except Exception as exc:
            logger.exception("ChainLoadWorker failed")
            self.signals.failed.emit(str(exc))


# ── Widget ────────────────────────────────────────────────────────────────────

class OptionChainWidget(BaseWidget):
    """Live option chain viewer.

    Displays CE on the left, Strike in the centre, PE on the right.
    All strike rows are fed by MarketFeed SNAP_QUOTE subscriptions.
    The underlying index/stock token is subscribed in LTP mode for the spot bar.
    """

    widget_id = "option_chain"

    # Bridge: tick arrived on feed thread → process on Qt main thread
    tick_arrived       = Signal(object, str)   # Tick, "CE" | "PE"
    underlying_ticked  = Signal(float)         # underlying LTP

    # Chain loaded on worker thread → update UI on main thread
    _chain_ready = Signal(list, float, list, str, str)
    _chain_error = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Option Chain", parent)
        self.setMinimumWidth(700)

        # State
        self._underlying_name: str = ""
        self._current_expiry:  str = ""
        self._underlying_ltp:  float = 0.0
        self._rows:            list[OptionChainRow] = []   # full strike list for the expiry
        self._visible_rows:    list[OptionChainRow] = []   # filtered window around ATM
        self._underlying_token:  str = ""
        self._underlying_exchange: str = "NSE"

        # Per-symbol strikes-per-side settings: {"NIFTY": 20, "BANKNIFTY": 15, ...}
        self._strikes_per_side: dict[str, int] = {}

        # Token → strike lookup for fast IV calculation
        self._ce_token_strike: dict[str, float] = {}
        self._pe_token_strike: dict[str, float] = {}

        # OI baseline per token: first OI seen after chain load.
        # OI Chg = current_oi - baseline_oi (intraday delta).
        # open_interest_change_percentage from Angel's binary feed is not
        # a usable absolute change value, so we compute it ourselves.
        self._oi_baseline: dict[str, int] = {}

        self._model = OptionChainModel()

        self._build_ui()

        # Wire signals
        self.tick_arrived.connect(self._on_tick_ui)
        self.underlying_ticked.connect(self._on_underlying_ltp_ui)
        self._chain_ready.connect(self._on_chain_ready)
        self._chain_error.connect(self._on_chain_error)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        content = QWidget()
        content.setStyleSheet(_QSS)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(6, 4, 6, 4)
        toolbar_layout.setSpacing(6)

        self._underlying_input = QLineEdit()
        self._underlying_input.setPlaceholderText("Underlying  (e.g. NIFTY)")
        self._underlying_input.setFixedWidth(160)
        self._underlying_input.returnPressed.connect(self._trigger_load)
        toolbar_layout.addWidget(self._underlying_input)

        search_btn = QPushButton("Search")
        search_btn.setFixedWidth(60)
        search_btn.clicked.connect(self._trigger_load)
        toolbar_layout.addWidget(search_btn)

        toolbar_layout.addSpacing(4)

        expiry_label = QLabel("Expiry:")
        expiry_label.setStyleSheet("color: #8b949e;")
        toolbar_layout.addWidget(expiry_label)

        self._expiry_combo = QComboBox()
        self._expiry_combo.setFixedWidth(110)
        self._expiry_combo.currentTextChanged.connect(self._on_expiry_changed)
        toolbar_layout.addWidget(self._expiry_combo)

        toolbar_layout.addSpacing(4)

        col_btn = QPushButton("Columns ⚙")
        col_btn.setFixedWidth(90)
        col_btn.clicked.connect(self._open_column_selector)
        toolbar_layout.addWidget(col_btn)

        settings_btn = QPushButton("Settings ⚙")
        settings_btn.setFixedWidth(90)
        settings_btn.clicked.connect(self._open_settings_dialog)
        toolbar_layout.addWidget(settings_btn)

        toolbar_layout.addStretch()

        self._status_label = QLabel("Enter an underlying and press Search")
        self._status_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        toolbar_layout.addWidget(self._status_label)

        root.addWidget(toolbar)

        # ── Underlying LTP bar ────────────────────────────────────────
        self._ltp_bar = QFrame()
        self._ltp_bar.setObjectName("ltpBar")
        self._ltp_bar.setFixedHeight(28)
        ltp_bar_layout = QHBoxLayout(self._ltp_bar)
        ltp_bar_layout.setContentsMargins(10, 0, 10, 0)

        self._ltp_name_lbl  = QLabel()
        self._ltp_price_lbl = QLabel()
        self._ltp_chg_lbl   = QLabel()
        self._ltp_atm_lbl   = QLabel()

        bold = QFont()
        bold.setBold(True)
        bold.setPointSize(10)
        self._ltp_price_lbl.setFont(bold)

        for lbl in (self._ltp_name_lbl, self._ltp_price_lbl, self._ltp_chg_lbl, self._ltp_atm_lbl):
            ltp_bar_layout.addWidget(lbl)
        ltp_bar_layout.addStretch()

        root.addWidget(self._ltp_bar)

        # ── Table ─────────────────────────────────────────────────────
        self._table = QTableView()
        self._table.setModel(self._model)
        header = OptionChainHeaderView(self._table)
        self._table.setHorizontalHeader(header)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setShowGrid(True)
        self._table.verticalHeader().setDefaultSectionSize(22)
        root.addWidget(self._table)

        self.setWidget(content)
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        for col_idx, col in enumerate(self._model.visible_columns()):
            self._table.setColumnWidth(col_idx, col.width)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _trigger_load(self) -> None:
        name = self._underlying_input.text().upper().strip()
        if not name:
            return
        self._load_chain(name, "")

    def _on_expiry_changed(self, expiry: str) -> None:
        if expiry and self._underlying_name and expiry != self._current_expiry:
            self._load_chain(self._underlying_name, expiry)

    def _open_column_selector(self) -> None:
        dlg = ColumnSelectorDialog(self)
        dlg.columns_changed.connect(self._on_columns_changed)
        dlg.exec()

    def _on_columns_changed(self) -> None:
        self._model.beginResetModel()
        self._model.endResetModel()
        self._apply_column_widths()

    def _open_settings_dialog(self) -> None:
        symbol = self._underlying_name or self._underlying_input.text().upper().strip()
        current_n = self._get_strikes_per_side(symbol)
        dlg = _StrikesSettingsDialog(symbol, current_n, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            n = dlg.value()
            key = symbol if symbol else "__default__"
            self._strikes_per_side[key] = n
            # If a chain is already loaded, re-filter immediately
            if self._rows:
                self._refilter_visible_rows()

    # ------------------------------------------------------------------
    # Strike filtering helpers
    # ------------------------------------------------------------------

    def _get_strikes_per_side(self, symbol: str = "") -> int:
        """Return the configured N for the given symbol (falls back to default 20)."""
        s = symbol or self._underlying_name
        if s and s in self._strikes_per_side:
            return self._strikes_per_side[s]
        return self._strikes_per_side.get("__default__", _DEFAULT_STRIKES_PER_SIDE)

    def _filter_rows_around_atm(
        self, rows: list[OptionChainRow], underlying_ltp: float
    ) -> list[OptionChainRow]:
        """Return at most (2×N + 1) rows centred on the ATM strike."""
        if not rows:
            return rows
        n = self._get_strikes_per_side()
        if underlying_ltp > 0:
            atm_strike = builder.get_atm_strike(rows, underlying_ltp)
            atm_idx = next(
                (i for i, r in enumerate(rows) if r.strike == atm_strike),
                len(rows) // 2,
            )
        else:
            atm_idx = len(rows) // 2
        lo = max(0, atm_idx - n)
        hi = min(len(rows) - 1, atm_idx + n)
        return rows[lo : hi + 1]

    def _unsubscribe_chain_token(self, token: str, callback) -> None:
        """Surgically unsubscribe one chain token and remove it from the tracking list."""
        from feed.market_feed import MarketFeed
        MarketFeed.instance().unsubscribe("NFO", token, callback)
        self._feed_subscriptions = [
            (e, t, cb, m) for e, t, cb, m in self._feed_subscriptions
            if not (e == "NFO" and t == token and cb == callback)
        ]

    def _refilter_visible_rows(self) -> None:
        """Re-apply the N-strikes filter to the current full rows, updating
        subscriptions surgically (unsubscribe out-of-window, subscribe newly in-window)
        and refreshing the model."""
        if not self._rows:
            return
        ltp = self._underlying_ltp
        new_visible = self._filter_rows_around_atm(self._rows, ltp)

        old_ce = {r.ce_token for r in self._visible_rows if r.ce_token}
        old_pe = {r.pe_token for r in self._visible_rows if r.pe_token}
        new_ce = {r.ce_token for r in new_visible if r.ce_token}
        new_pe = {r.pe_token for r in new_visible if r.pe_token}

        for token in old_ce - new_ce:
            self._unsubscribe_chain_token(token, self._on_ce_tick)
        for token in old_pe - new_pe:
            self._unsubscribe_chain_token(token, self._on_pe_tick)
        for r in new_visible:
            if r.ce_token and r.ce_token not in old_ce:
                self.subscribe_feed(
                    "NFO", r.ce_token, self._on_ce_tick, SubscriptionMode.SNAP_QUOTE
                )
            if r.pe_token and r.pe_token not in old_pe:
                self.subscribe_feed(
                    "NFO", r.pe_token, self._on_pe_tick, SubscriptionMode.SNAP_QUOTE
                )

        self._visible_rows = new_visible
        atm_strike = (
            builder.get_atm_strike(new_visible, ltp)
            if ltp > 0 and new_visible
            else (new_visible[len(new_visible) // 2].strike if new_visible else 0.0)
        )
        self._model.set_rows(new_visible, atm_strike)
        if ltp > 0:
            self._model.update_atm(ltp)
        self._apply_column_widths()
        self._scroll_to_atm()
        n = len(new_visible)
        self._status_label.setText(f"Live — {n} strikes")
        self._status_label.setStyleSheet("color: #3fb950; font-size: 11px;")

    def _maybe_recenter(self, ltp: float) -> None:
        """Re-center the strike window when ATM has moved outside the visible rows."""
        if not self._rows or not self._visible_rows:
            return
        atm_strike = builder.get_atm_strike(self._rows, ltp)
        if atm_strike not in {r.strike for r in self._visible_rows}:
            logger.info(
                "OptionChain: ATM %.0f moved out of visible window — re-centering",
                atm_strike,
            )
            self._refilter_visible_rows()

    # ------------------------------------------------------------------
    # Chain loading (worker thread)
    # ------------------------------------------------------------------

    def _load_chain(self, underlying_name: str, expiry: str) -> None:
        self._status_label.setText("Loading…")
        self._status_label.setStyleSheet("color: #f0c040; font-size: 11px;")

        # Unsubscribe previous chain tokens before loading new ones
        self._unsubscribe_all_feeds()
        self._ce_token_strike.clear()
        self._pe_token_strike.clear()

        worker = _ChainLoadWorker(underlying_name, expiry)
        worker.signals.finished.connect(self._chain_ready)
        worker.signals.failed.connect(self._chain_error)
        QThreadPool.globalInstance().start(worker)

    def _on_chain_ready(
        self,
        rows: list[OptionChainRow],
        underlying_ltp: float,
        expiries: list[str],
        expiry: str,
        underlying_exchange: str,
    ) -> None:
        # Recover underlying name from the input field (worker already uppercased it)
        self._underlying_name = self._underlying_input.text().upper().strip()
        self._current_expiry  = expiry
        self._underlying_ltp  = underlying_ltp
        self._rows            = rows          # full strike list for the expiry
        self._underlying_exchange = underlying_exchange

        # Reset OI baseline so the first tick for each token after a chain
        # reload becomes the new reference point for OI Chg calculation.
        self._oi_baseline.clear()

        # Build token→strike lookup over full row set (subscribed subset is smaller
        # but having extra entries is harmless — only subscribed tokens send ticks)
        self._ce_token_strike = {r.ce_token: r.strike for r in rows if r.ce_token}
        self._pe_token_strike = {r.pe_token: r.strike for r in rows if r.pe_token}

        # Apply N-strikes filter around ATM
        self._visible_rows = self._filter_rows_around_atm(rows, underlying_ltp)
        atm_strike = (
            builder.get_atm_strike(self._visible_rows, underlying_ltp)
            if underlying_ltp > 0 and self._visible_rows
            else (self._visible_rows[len(self._visible_rows) // 2].strike if self._visible_rows else 0.0)
        )

        # Update model with filtered rows only
        self._model.set_rows(self._visible_rows, atm_strike)
        if underlying_ltp > 0:
            self._model.update_atm(underlying_ltp)

        # Populate expiry combo (block signals to avoid re-triggering load)
        self._expiry_combo.blockSignals(True)
        self._expiry_combo.clear()
        for exp in expiries:
            self._expiry_combo.addItem(exp)
        idx = self._expiry_combo.findText(expiry)
        if idx >= 0:
            self._expiry_combo.setCurrentIndex(idx)
        self._expiry_combo.blockSignals(False)

        # Apply column widths after model reset
        self._apply_column_widths()

        # Subscribe feeds for the visible (filtered) rows only
        self._subscribe_chain(self._visible_rows)

        # Subscribe underlying for spot price
        self._subscribe_underlying()

        # Update LTP bar
        self._refresh_ltp_bar()

        # Scroll to ATM
        self._scroll_to_atm()

        n = len(self._visible_rows)
        self._status_label.setText(f"Live — {n} strikes")
        self._status_label.setStyleSheet("color: #3fb950; font-size: 11px;")

    def _on_chain_error(self, message: str) -> None:
        self._status_label.setText(f"Error: {message}")
        self._status_label.setStyleSheet("color: #f85149; font-size: 11px;")
        logger.error("OptionChain load error: %s", message)

    # ------------------------------------------------------------------
    # Feed subscriptions
    # ------------------------------------------------------------------

    def _subscribe_chain(self, rows: list[OptionChainRow]) -> None:
        total_tokens = sum(
            (1 if r.ce_token else 0) + (1 if r.pe_token else 0) for r in rows
        )

        if total_tokens > _SUBSCRIPTION_LIMIT:
            logger.warning(
                "OptionChain: %d tokens exceeds limit %d — restricting to ±%d strikes of ATM",
                total_tokens,
                _SUBSCRIPTION_LIMIT,
                _STRIKE_WINDOW,
            )
            atm_idx = self._model.atm_row_index()
            lo = max(0, atm_idx - _STRIKE_WINDOW)
            hi = min(len(rows) - 1, atm_idx + _STRIKE_WINDOW)
            rows_to_sub = rows[lo : hi + 1]
        else:
            rows_to_sub = rows

        for row in rows_to_sub:
            if row.ce_token:
                self.subscribe_feed(
                    "NFO", row.ce_token, self._on_ce_tick, SubscriptionMode.SNAP_QUOTE
                )
            if row.pe_token:
                self.subscribe_feed(
                    "NFO", row.pe_token, self._on_pe_tick, SubscriptionMode.SNAP_QUOTE
                )

    def _subscribe_underlying(self) -> None:
        info = INDEX_TOKENS.get(self._underlying_name)
        if info:
            self._underlying_token    = info["token"]
            self._underlying_exchange = info["exchange"]
            self.subscribe_feed(
                info["exchange"],
                info["token"],
                self._on_underlying_tick,
                SubscriptionMode.LTP,
            )
        else:
            # Stock option — try to find equity token
            try:
                from broker.instrument_master import InstrumentMaster
                results = InstrumentMaster.search(
                    f"{self._underlying_name}-EQ", exchange="NSE", max_results=3
                )
                if results:
                    inst = results[0]
                    self._underlying_token    = inst.token
                    self._underlying_exchange = inst.exchange
                    self.subscribe_feed(
                        inst.exchange, inst.token, self._on_underlying_tick, SubscriptionMode.LTP
                    )
            except Exception as exc:
                logger.warning("Could not subscribe underlying feed: %s", exc)

    # ------------------------------------------------------------------
    # Tick callbacks (feed thread → signal → main thread)
    # ------------------------------------------------------------------

    def _on_ce_tick(self, tick: Tick) -> None:
        self.tick_arrived.emit(tick, "CE")

    def _on_pe_tick(self, tick: Tick) -> None:
        self.tick_arrived.emit(tick, "PE")

    def _on_underlying_tick(self, tick: Tick) -> None:
        self.underlying_ticked.emit(tick.ltp)

    # ------------------------------------------------------------------
    # UI-thread tick handlers
    # ------------------------------------------------------------------

    def _on_tick_ui(self, tick: Tick, side: str) -> None:
        ltp    = tick.ltp
        volume = tick.volume or 0
        oi     = tick.open_interest or 0

        # Compute OI change as delta from the first tick seen after chain load.
        # Angel One's open_interest_change_percentage binary field does not
        # contain a usable absolute OI change value, so we derive it ourselves.
        if oi > 0:
            if tick.token not in self._oi_baseline:
                self._oi_baseline[tick.token] = oi
            oi_change = oi - self._oi_baseline[tick.token]
        else:
            oi_change = 0

        T = self._time_to_expiry()

        if side == "CE":
            strike = self._ce_token_strike.get(tick.token, 0.0)
            iv     = (
                calculate_iv(ltp, self._underlying_ltp, strike, T, "CE")
                if T > 0 and ltp > 0 and self._underlying_ltp > 0 and strike > 0
                else 0.0
            )
            sigma  = iv / 100.0
            delta  = (
                calculate_delta(self._underlying_ltp, strike, T, sigma, "CE")
                if sigma > 0
                else 0.0
            )
            self._model.update_ce(tick.token, ltp, oi, oi_change, iv, delta, volume)
        else:
            strike = self._pe_token_strike.get(tick.token, 0.0)
            iv     = (
                calculate_iv(ltp, self._underlying_ltp, strike, T, "PE")
                if T > 0 and ltp > 0 and self._underlying_ltp > 0 and strike > 0
                else 0.0
            )
            sigma  = iv / 100.0
            delta  = (
                calculate_delta(self._underlying_ltp, strike, T, sigma, "PE")
                if sigma > 0
                else 0.0
            )
            self._model.update_pe(tick.token, ltp, oi, oi_change, iv, delta, volume)

    def _on_underlying_ltp_ui(self, ltp: float) -> None:
        self._underlying_ltp = ltp
        self._model.update_atm(ltp)
        self._refresh_ltp_bar()
        self._maybe_recenter(ltp)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _time_to_expiry(self) -> float:
        if not self._current_expiry:
            return 0.0
        try:
            expiry_date = datetime.strptime(self._current_expiry, "%d%b%Y").date()
            today = date.today()
            days  = (expiry_date - today).days
            return max(days / 365.0, 0.0)
        except ValueError:
            return 0.0

    def _refresh_ltp_bar(self) -> None:
        name = self._underlying_name
        ltp  = self._underlying_ltp

        self._ltp_name_lbl.setText(f"  {name}" if name else "")

        if ltp > 0:
            self._ltp_price_lbl.setText(f"  {ltp:,.2f}")
            self._ltp_price_lbl.setStyleSheet("color: #e6edf3; font-weight: bold;")
        else:
            self._ltp_price_lbl.setText("")

        atm_strike = self._model._atm_strike
        if atm_strike:
            self._ltp_atm_lbl.setText(f"     ATM: {atm_strike:.0f}")
            self._ltp_atm_lbl.setStyleSheet("color: #f0c040;")
        else:
            self._ltp_atm_lbl.setText("")

    def _scroll_to_atm(self) -> None:
        atm_idx = self._model.atm_row_index()
        if atm_idx >= 0:
            self._table.scrollTo(
                self._model.index(atm_idx, 0),
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        if self._underlying_name:
            self._load_chain(self._underlying_name, self._current_expiry)

    def on_hide(self) -> None:
        # _unsubscribe_all_feeds() is called by BaseWidget automatically
        pass

    def save_state(self) -> dict:
        return {
            "underlying":       self._underlying_name,
            "expiry":           self._current_expiry,
            "visible_columns":  [c.key for c in ALL_COLUMNS if c.visible],
            "strikes_per_side": dict(self._strikes_per_side),
        }

    def restore_state(self, state: dict) -> None:
        underlying = state.get("underlying", "")
        expiry     = state.get("expiry", "")
        vis_keys   = set(state.get("visible_columns", []))

        if vis_keys:
            for col in ALL_COLUMNS:
                col.visible = col.key in vis_keys

        self._strikes_per_side = dict(state.get("strikes_per_side", {}))

        if underlying:
            self._underlying_input.setText(underlying)
            self._load_chain(underlying, expiry)
