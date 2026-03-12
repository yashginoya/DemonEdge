"""Market Depth — standalone OS window with live 5-level order book and full quote."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from feed.feed_models import SubscriptionMode
from models.instrument import Instrument
from models.tick import Tick
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_GREEN  = "#3fb950"
_RED    = "#f85149"
_MUTED  = "#8b949e"
_FG     = "#e6edf3"
_FG_DIM = "#c9d1d9"
_BG     = "#0d1117"
_BG2    = "#161b22"
_BORDER = "#21262d"

_DASH = "—"

# Fixed-height constants used to compute the locked window height.
_SEARCH_H = 34   # single combined header row (symbol + LTP + change + search)
_ROW_H    = 26   # each depth-table row
_RATIO_H  = 6    # bid/ask ratio bar
_TOTALS_H = 26   # total-qty row

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


def _fmt_indian(v: int | float | None) -> str:
    """Format a large integer with Indian-style comma grouping (no unit conversion).

    e.g. 17184554 → '1,71,84,554'
    """
    if v is None:
        return _DASH
    n = int(v)
    s = str(n)
    if len(s) <= 3:
        return s
    # last 3 digits, then groups of 2
    result = s[-3:]
    s = s[:-3]
    while s:
        result = s[-2:] + "," + result
        s = s[:-2]
    return result


def _lbl(
    text: str,
    colour: str = _MUTED,
    bold: bool = False,
    align=Qt.AlignmentFlag.AlignLeft,
) -> QLabel:
    w = QLabel(text)
    style = f"color: {colour}; font-size: 11px;"
    if bold:
        style += " font-weight: bold;"
    w.setStyleSheet(style)
    w.setAlignment(align)
    return w


def _val(text: str = _DASH, align=Qt.AlignmentFlag.AlignRight) -> QLabel:
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
        self.setFixedHeight(_RATIO_H)
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
_N_LEVELS   = 5


class _DepthTable(QTableWidget):
    """5-level order book table. Left: bids (green), right: asks (red)."""

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

        self.verticalHeader().setDefaultSectionSize(_ROW_H)
        self._populate_empty()

    def _make_item(
        self, text: str, colour: str, align: Qt.AlignmentFlag
    ) -> QTableWidgetItem:
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
        bqty: str, bord: str, bprice: str,
        aprice: str, aord: str, aqty: str,
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
        for i in range(_N_LEVELS):
            if i < len(buy_levels):
                b = buy_levels[i]
                bprice, bqty, bord = _fmt_price(b.price), _fmt_qty(b.quantity), str(b.orders)
            else:
                bprice = bqty = bord = _DASH

            if i < len(sell_levels):
                s = sell_levels[i]
                aprice, aqty, aord = _fmt_price(s.price), _fmt_qty(s.quantity), str(s.orders)
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
    ("Open",      "open",  "High",      "high"),
    ("Low",       "low",   "Prev Close","close"),
    ("Avg Price", "atp",   "Volume",    "volume"),
    ("OI",        "oi",    "LTQ",       "ltq"),
    ("LTT",       "ltt",   "LCL",       "lcl"),
    ("UCL",       "ucl",   "52W High",  "w52h"),
    ("52W Low",   "w52l",  "",          ""),
]


class _QuoteGrid(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._vals: dict[str, QLabel] = {}
        self._build()

    def _build(self) -> None:
        grid = QGridLayout(self)
        # Fix 1: tight margins and minimal row spacing
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
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
        # No addStretch — grid sits at natural height

    def reset(self) -> None:
        for v in self._vals.values():
            v.setText(_DASH)

    def refresh_tick(self, tick: Tick) -> None:
        """Update quote labels from a Tick, skipping any field that is None.

        Angel One sends two ticks in rapid succession — one with full SNAP_QUOTE
        data and one with only LTP (all quote fields None).  Skipping None values
        keeps the last known-good value on screen instead of flickering to '—'.
        Named refresh_tick (not update) to avoid shadowing QWidget.update().
        """
        logger.debug(
            "QuoteGrid.refresh_tick: close=%s vol=%s open=%s",
            tick.close, tick.volume, tick.open,
        )

        def _s(key: str, text: str | None) -> None:
            if text is not None and key in self._vals:
                self._vals[key].setText(text)

        def _price(v: float | None) -> str | None:
            return None if v is None else _fmt_price(v)

        def _vol(v: int | float | None) -> str | None:
            return None if v is None else _fmt_indian(v)

        def _qty(v: int | float | None) -> str | None:
            return None if v is None else _fmt_qty(v)

        _s("open",   _price(tick.open))
        _s("high",   _price(tick.high))
        _s("low",    _price(tick.low))
        _s("close",  _price(tick.close))
        _s("atp",    _price(tick.average_traded_price))
        _s("volume", _vol(tick.volume))
        _s("oi",     _vol(tick.open_interest))
        _s("ltq",    _qty(tick.last_traded_quantity))
        _s("lcl",    _price(tick.lower_circuit_limit))
        _s("ucl",    _price(tick.upper_circuit_limit))
        _s("w52h",   _price(tick.week_52_high))
        _s("w52l",   _price(tick.week_52_low))

        if tick.last_traded_time is not None:
            _s("ltt", tick.last_traded_time.strftime("%H:%M:%S"))


# ---------------------------------------------------------------------------
# Market Depth standalone window
# ---------------------------------------------------------------------------

class MarketDepthWindow(QWidget):
    """Live 5-level market depth and full quote — standalone OS window.

    Opened via F5, Command Palette, or View → Add Widget.  Multiple instances
    are allowed; each launch creates an independent window.  Parent is None so
    the window is not minimised with the main terminal.

    Window title: "DemonEdge - Market Depth" per CLAUDE.md convention.
    """

    widget_id = "market_depth"  # kept for WidgetRegistry discoverability

    # Signal bridge: feed thread → Qt main thread
    _tick_arrived = Signal(object)  # Tick

    # Emitted just before the window is destroyed so MainWindow can clean up
    window_closed = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("DemonEdge - Market Depth")

        self._instrument: Instrument | None = None
        self._prev_ltp: float = 0.0
        # Feed subscriptions managed directly (no BaseWidget helper)
        self._feed_subs: list[tuple[str, str, Callable]] = []

        self._build_ui()
        self._tick_arrived.connect(self._on_tick_ui)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background: {_BG};")
        self.setMinimumWidth(720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- Combined header row: symbol · LTP · change · [Search] ----
        header_row = QWidget()
        header_row.setStyleSheet(
            f"background: {_BG2}; border-bottom: 1px solid {_BORDER};"
        )
        header_row.setFixedHeight(_SEARCH_H)
        hl = QHBoxLayout(header_row)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(0)

        self._symbol_label = QLabel("No symbol selected")
        self._symbol_label.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; background: transparent;"
        )

        self._ltp_label = QLabel(_DASH)
        ltp_font = QFont()
        ltp_font.setPointSize(12)
        ltp_font.setBold(True)
        self._ltp_label.setFont(ltp_font)
        self._ltp_label.setStyleSheet(f"color: {_FG}; background: transparent;")
        self._ltp_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._change_label = QLabel("")
        self._change_label.setStyleSheet(
            f"color: {_MUTED}; font-size: 12px; background: transparent;"
        )
        self._change_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Search box — auto-focused on show; Return opens SearchDialog
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("⌕  Search symbol…")
        self._search_box.setFixedHeight(24)
        self._search_box.setFixedWidth(160)
        self._search_box.setStyleSheet(
            f"QLineEdit {{ background: {_BG}; color: {_MUTED}; border: 1px solid {_BORDER};"
            f" border-radius: 4px; font-size: 11px; padding: 0 8px; }}"
            f"QLineEdit:focus {{ border-color: #58a6ff; color: {_FG}; }}"
        )
        self._search_box.returnPressed.connect(self._open_search)

        hl.addWidget(self._symbol_label)
        hl.addSpacing(12)
        hl.addWidget(self._ltp_label)
        hl.addSpacing(8)
        hl.addWidget(self._change_label)
        hl.addStretch(1)
        hl.addWidget(self._search_box)
        layout.addWidget(header_row)

        # ---- Horizontal splitter: depth (left) | quote grid (right) ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {_BORDER}; width: 1px; }}"
        )

        # -- Left panel: depth table + ratio bar + total qty --
        left = QWidget()
        left.setStyleSheet(f"background: {_BG};")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Depth table — measure header height before adding to layout
        self._depth_table = _DepthTable()
        hh_h = max(self._depth_table.horizontalHeader().sizeHint().height(), 20)
        depth_table_h = hh_h + _N_LEVELS * _ROW_H + 2
        self._depth_table.setFixedHeight(depth_table_h)
        left_layout.addWidget(self._depth_table)

        self._ratio_bar = _RatioBar()
        left_layout.addWidget(self._ratio_bar)

        totals = QWidget()
        totals.setFixedHeight(_TOTALS_H)
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
        self._total_ask_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        tl.addWidget(self._total_bid_label)
        tl.addWidget(total_center)
        tl.addWidget(self._total_ask_label)
        left_layout.addWidget(totals)
        # No addStretch — content is top-aligned, panel height matches content

        splitter.addWidget(left)

        # -- Right panel: quote grid in scroll area --
        self._quote_grid = _QuoteGrid()
        self._quote_grid.setStyleSheet(f"background: {_BG};")

        right_scroll = QScrollArea()
        right_scroll.setWidget(self._quote_grid)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setStyleSheet(
            f"QScrollArea {{ background: {_BG}; border: none; }}"
            f"QScrollBar:vertical {{ background: {_BG2}; width: 6px; border: none; }}"
            f"QScrollBar::handle:vertical {{ background: {_BORDER}; border-radius: 3px; }}"
        )
        splitter.addWidget(right_scroll)

        splitter.setSizes([380, 340])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        layout.addWidget(splitter, 1)

        # Lock window height — single header + depth body, no vertical resize
        fixed_h = _SEARCH_H + depth_table_h + _RATIO_H + _TOTALS_H
        self.setFixedHeight(fixed_h)

    # ------------------------------------------------------------------
    # Feed management (replaces BaseWidget helper)
    # ------------------------------------------------------------------

    def _subscribe_feed(
        self,
        exchange: str,
        token: str,
        callback: Callable,
        mode: int,
    ) -> None:
        from feed.market_feed import MarketFeed
        MarketFeed.instance().subscribe(exchange, token, callback, mode)
        self._feed_subs.append((exchange, token, callback))

    def _unsubscribe_all_feeds(self) -> None:
        from feed.market_feed import MarketFeed
        feed = MarketFeed.instance()
        for exchange, token, cb in self._feed_subs:
            feed.unsubscribe(exchange, token, cb)
        self._feed_subs.clear()

    # ------------------------------------------------------------------
    # Search / instrument load
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        """Auto-focus the search box each time the window is shown."""
        super().showEvent(event)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._search_box.setFocus)
        QTimer.singleShot(0, self._search_box.selectAll)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def _open_search(self) -> None:
        from widgets.watchlist.search_dialog import SearchDialog
        dlg = SearchDialog(self)
        dlg.instrument_selected.connect(self._load_instrument)
        dlg.show()
        self._search_box.clear()

    def _load_instrument(self, instrument: Instrument) -> None:
        """Switch to a new instrument: unsubscribe old, subscribe new."""
        self._unsubscribe_all_feeds()
        self._instrument = instrument
        self._prev_ltp = 0.0

        exch = instrument.exchange
        self._symbol_label.setText(f"{instrument.symbol}  ·  {exch}")
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

        self._subscribe_feed(
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
    # Close event
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self._unsubscribe_all_feeds()
        self.window_closed.emit()
        event.accept()

    # ------------------------------------------------------------------
    # Tick update — unchanged from original
    # ------------------------------------------------------------------

    def _on_tick_ui(self, tick: Tick) -> None:
        """Main thread — update all display elements from tick."""
        ltp = tick.ltp

        prev_close = tick.close or 0.0
        if prev_close > 0:
            change = ltp - prev_close
            change_pct = change / prev_close * 100
            colour = _GREEN if change >= 0 else _RED
            sign = "+" if change >= 0 else ""
            self._ltp_label.setStyleSheet(f"color: {colour}; background: transparent;")
            self._change_label.setText(
                f"{sign}{change:.2f}  ({sign}{change_pct:.2f}%)"
            )
            self._change_label.setStyleSheet(
                f"color: {colour}; font-size: 12px; background: transparent;"
            )
        else:
            self._ltp_label.setStyleSheet(f"color: {_FG}; background: transparent;")

        self._ltp_label.setText(f"{ltp:,.2f}")
        self._prev_ltp = ltp

        if tick.depth_buy or tick.depth_sell:
            self._depth_table.update_depth(tick.depth_buy, tick.depth_sell)

        tbq = tick.total_buy_quantity
        tsq = tick.total_sell_quantity
        if tbq is not None:
            self._total_bid_label.setText(_fmt_qty(tbq))
        if tsq is not None:
            self._total_ask_label.setText(_fmt_qty(tsq))
        if tbq is not None and tsq is not None:
            self._ratio_bar.set_ratio(tbq, tsq)

        self._quote_grid.refresh_tick(tick)


# ---------------------------------------------------------------------------
# Self-registration — keeps the entry in WidgetRegistry for Command Palette
# discoverability.  MainWindow.spawn_widget() intercepts "market_depth" and
# opens a MarketDepthWindow directly rather than going through the dock flow.
# ---------------------------------------------------------------------------

from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=MarketDepthWindow.widget_id,
        display_name="Market Depth",
        category="Market Data",
        factory=MarketDepthWindow,  # type: ignore[arg-type]
        description="Live 5-level order book with full quote and circuit limits",
    )
)
