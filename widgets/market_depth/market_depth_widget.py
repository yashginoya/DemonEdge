"""Market Depth & Quote widget — live 5-level order book with full SNAP_QUOTE data."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from feed.feed_models import SubscriptionMode
from models.instrument import Instrument
from models.tick import Tick
from utils.logger import get_logger
from widgets.base_widget import BaseWidget

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_GREEN = "#3fb950"
_RED = "#f85149"
_MUTED = "#8b949e"
_FG = "#e6edf3"
_FG_DIM = "#c9d1d9"
_BG = "#0d1117"
_BG2 = "#161b22"
_BORDER = "#21262d"

_DASH = "—"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_price(v: float | None, decimals: int = 2) -> str:
    if v is None or v == 0.0:
        return _DASH
    return f"{v:,.{decimals}f}"


def _fmt_qty(v: int | float | None) -> str:
    if v is None:
        return _DASH
    n = int(v)
    if n >= 10_000_000:
        return f"{n / 1_000_000:.1f}Cr"
    if n >= 100_000:
        return f"{n / 100_000:.2f}L"
    return f"{n:,}"


def _fmt_vol(v: int | None) -> str:
    if v is None:
        return _DASH
    if v >= 10_000_000:
        return f"{v / 1_000_000:.2f}Cr"
    if v >= 100_000:
        return f"{v / 100_000:.2f}L"
    return f"{v:,}"


def _lbl(text: str, colour: str = _MUTED, bold: bool = False, align=Qt.AlignmentFlag.AlignLeft) -> QLabel:
    """Create a small styled QLabel."""
    w = QLabel(text)
    style = f"color: {colour}; font-size: 11px;"
    if bold:
        style += " font-weight: bold;"
    w.setStyleSheet(style)
    w.setAlignment(align)
    return w


def _val(text: str = _DASH, align=Qt.AlignmentFlag.AlignRight) -> QLabel:
    """Create a value QLabel (white, right-aligned, mono)."""
    w = QLabel(text)
    w.setStyleSheet(
        f"color: {_FG}; font-size: 11px;"
        " font-family: 'Consolas', 'Courier New', monospace;"
    )
    w.setAlignment(align)
    return w


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {_BORDER};")
    return f


# ---------------------------------------------------------------------------
# Ratio bar
# ---------------------------------------------------------------------------

class _RatioBar(QProgressBar):
    """Horizontal bar: green (bid) fills left, red (ask) fills right."""

    def __init__(self) -> None:
        super().__init__()
        self.setRange(0, 1000)
        self.setValue(500)
        self.setTextVisible(False)
        self.setFixedHeight(6)
        self.setStyleSheet(
            f"QProgressBar {{ background: {_RED}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {_GREEN}; border-radius: 3px; }}"
        )

    def set_ratio(self, bid: float, ask: float) -> None:
        total = bid + ask
        if total <= 0:
            self.setValue(500)
            return
        self.setValue(int(bid / total * 1000))


# ---------------------------------------------------------------------------
# Depth table
# ---------------------------------------------------------------------------

_DEPTH_COLS = ["Qty", "Orders", "Bid Price", "Ask Price", "Orders", "Qty"]
_N_LEVELS = 5


class _DepthTable(QTableWidget):
    """5-level order book table. Left: bids, right: asks."""

    def __init__(self) -> None:
        super().__init__(_N_LEVELS, 6)
        self.setHorizontalHeaderLabels(_DEPTH_COLS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setShowGrid(False)

        self.setStyleSheet(
            f"QTableWidget {{ background: {_BG}; border: none; gridline-color: {_BORDER}; }}"
            f"QHeaderView::section {{"
            f"  background: {_BG2}; color: {_MUTED}; font-size: 10px;"
            f"  border: none; border-bottom: 1px solid {_BORDER}; padding: 3px 4px;"
            f"}}"
            "QTableWidget::item { padding: 0 6px; border: none; }"
        )

        # Column stretching
        hh = self.horizontalHeader()
        hh.setDefaultSectionSize(60)
        hh.setSectionResizeMode(0, hh.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, hh.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, hh.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, hh.ResizeMode.Fixed)
        hh.setSectionResizeMode(4, hh.ResizeMode.Fixed)
        hh.setSectionResizeMode(5, hh.ResizeMode.Stretch)
        self.setColumnWidth(1, 50)
        self.setColumnWidth(2, 80)
        self.setColumnWidth(3, 80)
        self.setColumnWidth(4, 50)

        self.verticalHeader().setDefaultSectionSize(26)

        self._populate_empty()

    def _make_item(self, text: str, colour: str, align: Qt.AlignmentFlag) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setForeground(QColor(colour))
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _populate_empty(self) -> None:
        for row in range(_N_LEVELS):
            self._set_row(row, _DASH, _DASH, _DASH, _DASH, _DASH, _DASH)

    def _set_row(
        self,
        row: int,
        bqty: str,
        bord: str,
        bprice: str,
        aprice: str,
        aord: str,
        aqty: str,
    ) -> None:
        ra = Qt.AlignmentFlag.AlignRight
        la = Qt.AlignmentFlag.AlignLeft
        self.setItem(row, 0, self._make_item(bqty,   _FG_DIM, ra))
        self.setItem(row, 1, self._make_item(bord,   _MUTED,  ra))
        self.setItem(row, 2, self._make_item(bprice, _GREEN,  ra))
        self.setItem(row, 3, self._make_item(aprice, _RED,    la))
        self.setItem(row, 4, self._make_item(aord,   _MUTED,  la))
        self.setItem(row, 5, self._make_item(aqty,   _FG_DIM, la))

    def update_depth(self, buy_levels, sell_levels) -> None:
        """Update table with new depth data. Lists may be shorter than 5."""
        for i in range(_N_LEVELS):
            if i < len(buy_levels):
                b = buy_levels[i]
                bprice = _fmt_price(b.price)
                bqty = _fmt_qty(b.quantity)
                bord = str(b.orders)
            else:
                bprice = bqty = bord = _DASH

            if i < len(sell_levels):
                s = sell_levels[i]
                aprice = _fmt_price(s.price)
                aqty = _fmt_qty(s.quantity)
                aord = str(s.orders)
            else:
                aprice = aqty = aord = _DASH

            self._set_row(i, bqty, bord, bprice, aprice, aord, aqty)

    def clear_depth(self) -> None:
        self._populate_empty()


# ---------------------------------------------------------------------------
# Quote grid
# ---------------------------------------------------------------------------

_QUOTE_FIELDS: list[tuple[str, str, str, str]] = [
    # (left_label, left_key, right_label, right_key)
    ("Open",       "open",    "High",      "high"),
    ("Low",        "low",     "Prev Close","close"),
    ("Avg Price",  "atp",     "Volume",    "volume"),
    ("OI",         "oi",      "LTQ",       "ltq"),
    ("LTT",        "ltt",     "LCL",       "lcl"),
    ("UCL",        "ucl",     "52W High",  "w52h"),
    ("52W Low",    "w52l",    "",          ""),
]


class _QuoteGrid(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._vals: dict[str, QLabel] = {}
        self._build()

    def _build(self) -> None:
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        for row_idx, (ll, lk, rl, rk) in enumerate(_QUOTE_FIELDS):
            lbl_l = _lbl(ll + ":", align=Qt.AlignmentFlag.AlignLeft)
            val_l = _val()
            grid.addWidget(lbl_l, row_idx, 0)
            grid.addWidget(val_l, row_idx, 1)
            self._vals[lk] = val_l

            if rl:
                lbl_r = _lbl(rl + ":", align=Qt.AlignmentFlag.AlignLeft)
                val_r = _val()
                grid.addWidget(lbl_r, row_idx, 2)
                grid.addWidget(val_r, row_idx, 3)
                self._vals[rk] = val_r

    def reset(self) -> None:
        for v in self._vals.values():
            v.setText(_DASH)

    def update(self, tick: Tick) -> None:  # type: ignore[override]
        def _s(key: str, text: str) -> None:
            if key in self._vals:
                self._vals[key].setText(text)

        _s("open",   _fmt_price(tick.open))
        _s("high",   _fmt_price(tick.high))
        _s("low",    _fmt_price(tick.low))
        _s("close",  _fmt_price(tick.close))
        _s("atp",    _fmt_price(tick.average_traded_price))
        _s("volume", _fmt_vol(tick.volume))
        _s("oi",     _fmt_vol(tick.open_interest))
        _s("ltq",    _fmt_qty(tick.last_traded_quantity))
        _s("lcl",    _fmt_price(tick.lower_circuit_limit))
        _s("ucl",    _fmt_price(tick.upper_circuit_limit))
        _s("w52h",   _fmt_price(tick.week_52_high))
        _s("w52l",   _fmt_price(tick.week_52_low))

        if tick.last_traded_time:
            _s("ltt", tick.last_traded_time.strftime("%H:%M:%S"))
        else:
            _s("ltt", _DASH)


# ---------------------------------------------------------------------------
# Market Depth Widget
# ---------------------------------------------------------------------------

class MarketDepthWidget(BaseWidget):
    """Live 5-level market depth and full quote panel.

    Subscribes to SNAP_QUOTE mode (mode 3) for the selected symbol,
    which provides depth, OI, circuit limits, 52W range, and all quote fields.
    """

    widget_id = "market_depth"

    # Signal bridge: feed thread → Qt main thread
    _tick_arrived = Signal(object)  # Tick

    def __init__(self) -> None:
        super().__init__("Market Depth")
        self._instrument: Instrument | None = None
        self._prev_ltp: float = 0.0

        self._build_ui()
        self._tick_arrived.connect(self._on_tick_ui)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setStyleSheet(f"background: {_BG};")
        self.setWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- Symbol search bar ----
        search_row = QWidget()
        search_row.setStyleSheet(f"background: {_BG2};")
        search_row.setFixedHeight(34)
        sl = QHBoxLayout(search_row)
        sl.setContentsMargins(8, 4, 8, 4)
        sl.setSpacing(6)

        self._symbol_label = QLabel("No symbol selected")
        self._symbol_label.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; background: transparent;"
        )
        self._symbol_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self._search_btn = QPushButton("⌕ Search")
        self._search_btn.setFixedHeight(24)
        self._search_btn.setStyleSheet(
            f"QPushButton {{ background: {_BG}; color: {_MUTED}; border: 1px solid {_BORDER};"
            f" border-radius: 4px; font-size: 11px; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {_FG}; border-color: #58a6ff; }}"
        )
        self._search_btn.clicked.connect(self._open_search)

        sl.addWidget(self._symbol_label, 1)
        sl.addWidget(self._search_btn)
        layout.addWidget(search_row)

        # ---- LTP header ----
        header = QWidget()
        header.setStyleSheet(f"background: {_BG}; border-bottom: 1px solid {_BORDER};")
        header.setFixedHeight(46)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 4, 10, 4)

        self._ltp_label = QLabel(_DASH)
        ltp_font = QFont()
        ltp_font.setPointSize(18)
        ltp_font.setBold(True)
        self._ltp_label.setFont(ltp_font)
        self._ltp_label.setStyleSheet(f"color: {_FG}; background: transparent;")

        self._change_label = QLabel("")
        self._change_label.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; background: transparent;"
        )
        self._change_label.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)

        hl.addWidget(self._ltp_label)
        hl.addSpacing(10)
        hl.addWidget(self._change_label, 1)
        layout.addWidget(header)

        # ---- Depth table ----
        self._depth_table = _DepthTable()
        self._depth_table.setFixedHeight(
            self._depth_table.horizontalHeader().height()
            + _N_LEVELS * 26
            + 2
        )
        layout.addWidget(self._depth_table)

        # ---- Ratio bar ----
        self._ratio_bar = _RatioBar()
        layout.addWidget(self._ratio_bar)

        # ---- Total qty row ----
        totals = QWidget()
        totals.setFixedHeight(26)
        totals.setStyleSheet(f"background: {_BG2};")
        tl = QHBoxLayout(totals)
        tl.setContentsMargins(8, 2, 8, 2)

        self._total_bid_label = QLabel(_DASH)
        self._total_bid_label.setStyleSheet(
            f"color: {_GREEN}; font-size: 11px;"
            " font-family: 'Consolas', 'Courier New', monospace;"
        )

        total_center = _lbl("Total Qty", _MUTED, align=Qt.AlignmentFlag.AlignCenter)
        total_center.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self._total_ask_label = QLabel(_DASH)
        self._total_ask_label.setStyleSheet(
            f"color: {_RED}; font-size: 11px;"
            " font-family: 'Consolas', 'Courier New', monospace;"
        )
        self._total_ask_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        tl.addWidget(self._total_bid_label)
        tl.addWidget(total_center)
        tl.addWidget(self._total_ask_label)
        layout.addWidget(totals)

        layout.addWidget(_divider())

        # ---- Quote grid (scrollable) ----
        self._quote_grid = _QuoteGrid()
        self._quote_grid.setStyleSheet(f"background: {_BG};")

        scroll = QScrollArea()
        scroll.setWidget(self._quote_grid)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {_BG}; border: none; }}"
            f"QScrollBar:vertical {{ background: {_BG2}; width: 6px; border: none; }}"
            f"QScrollBar::handle:vertical {{ background: {_BORDER}; border-radius: 3px; }}"
        )
        layout.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    # Search / instrument load
    # ------------------------------------------------------------------

    def _open_search(self) -> None:
        from widgets.watchlist.search_dialog import SearchDialog
        dlg = SearchDialog(self)
        dlg.instrument_selected.connect(self._load_instrument)
        dlg.show()

    def _load_instrument(self, instrument: Instrument) -> None:
        """Switch to a new instrument: unsubscribe old, subscribe new."""
        self._unsubscribe_all_feeds()
        self._instrument = instrument
        self._prev_ltp = 0.0

        # Header labels
        exch = instrument.exchange
        self._symbol_label.setText(
            f"{instrument.symbol}  ·  {exch}"
        )
        self._symbol_label.setStyleSheet(
            f"color: {_FG}; font-size: 12px; font-weight: bold; background: transparent;"
        )
        self._ltp_label.setText(_DASH)
        self._ltp_label.setStyleSheet(f"color: {_FG}; background: transparent;")
        self._change_label.setText("")
        self._depth_table.clear_depth()
        self._ratio_bar.set_ratio(0, 0)
        self._total_bid_label.setText(_DASH)
        self._total_ask_label.setText(_DASH)
        self._quote_grid.reset()

        # Subscribe SNAP_QUOTE
        self.subscribe_feed(
            exch,
            instrument.token,
            self._on_tick_feed,
            SubscriptionMode.SNAP_QUOTE,
        )
        logger.debug("MarketDepth: subscribed %s:%s SNAP_QUOTE", exch, instrument.token)

    def _on_tick_feed(self, tick: Tick) -> None:
        """Feed thread callback — bridge to main thread."""
        self._tick_arrived.emit(tick)

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        if self._instrument:
            self.subscribe_feed(
                self._instrument.exchange,
                self._instrument.token,
                self._on_tick_feed,
                SubscriptionMode.SNAP_QUOTE,
            )

    def on_hide(self) -> None:
        pass  # BaseWidget._unsubscribe_all_feeds() is called automatically

    def save_state(self) -> dict:
        if not self._instrument:
            return {}
        return {
            "token": self._instrument.token,
            "exchange": self._instrument.exchange,
            "symbol": self._instrument.symbol,
            "name": self._instrument.name,
            "instrument_type": self._instrument.instrument_type,
            "expiry": self._instrument.expiry,
            "strike": self._instrument.strike,
            "lot_size": self._instrument.lot_size,
            "tick_size": self._instrument.tick_size,
        }

    def restore_state(self, state: dict) -> None:
        if not state.get("token"):
            return
        inst = Instrument(
            token=state["token"],
            exchange=state["exchange"],
            symbol=state["symbol"],
            name=state.get("name", ""),
            instrument_type=state.get("instrument_type", ""),
            expiry=state.get("expiry", ""),
            strike=state.get("strike", -1.0),
            lot_size=state.get("lot_size", 1),
            tick_size=state.get("tick_size", 0.05),
        )
        self._load_instrument(inst)

    # ------------------------------------------------------------------
    # Tick update
    # ------------------------------------------------------------------

    def _on_tick_ui(self, tick: Tick) -> None:
        """Main thread — update all display elements from tick."""
        ltp = tick.ltp

        # LTP and change colour
        prev_close = tick.close or 0.0
        if prev_close > 0:
            change = ltp - prev_close
            change_pct = change / prev_close * 100
            colour = _GREEN if change >= 0 else _RED
            sign = "+" if change >= 0 else ""
            self._ltp_label.setStyleSheet(
                f"color: {colour}; background: transparent;"
            )
            self._change_label.setText(
                f"{sign}{change:.2f}  ({sign}{change_pct:.2f}%)"
            )
            self._change_label.setStyleSheet(
                f"color: {colour}; font-size: 11px; background: transparent;"
            )
        else:
            self._ltp_label.setStyleSheet(f"color: {_FG}; background: transparent;")

        self._ltp_label.setText(f"{ltp:,.2f}")
        self._prev_ltp = ltp

        # Depth
        if tick.depth_buy or tick.depth_sell:
            self._depth_table.update_depth(tick.depth_buy, tick.depth_sell)

        # Total quantities
        tbq = tick.total_buy_quantity
        tsq = tick.total_sell_quantity
        if tbq is not None:
            self._total_bid_label.setText(_fmt_qty(tbq))
        if tsq is not None:
            self._total_ask_label.setText(_fmt_qty(tsq))
        if tbq is not None and tsq is not None:
            self._ratio_bar.set_ratio(tbq, tsq)

        # Quote grid
        self._quote_grid.update(tick)


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------

from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=MarketDepthWidget.widget_id,
        display_name="Market Depth",
        category="Market Data",
        factory=MarketDepthWidget,
        description="Live 5-level order book with full quote and circuit limits",
    )
)
