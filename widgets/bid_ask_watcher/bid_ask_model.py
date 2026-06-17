"""Table model for the Bid/Ask Quantity Watcher.

One row per underlying (a :class:`~widgets.bid_ask_watcher.ticker_watch.TickerWatch`).
The model only reads the live values off each TickerWatch; the widget tells the
model when a row changed.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from widgets.bid_ask_watcher.ticker_watch import TickerWatch

_GREEN = QColor("#3fb950")
_RED = QColor("#f85149")
_GREY = QColor("#8b949e")
_WHITE = QColor("#e6edf3")


def _fmt_qty(value: float) -> str:
    """Indian-style comma grouping for large integer quantities (no unit conversion)."""
    n = int(round(value))
    if n == 0:
        return "0"
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


class BidAskModel(QAbstractTableModel):
    COL_SYMBOL = 0
    COL_STRIKES = 1
    COL_ATM = 2
    COL_EXPIRY = 3
    COL_CALL_BID = 4
    COL_CALL_ASK = 5
    COL_CALL_RATIO = 6
    COL_PUT_BID = 7
    COL_PUT_ASK = 8
    COL_PUT_RATIO = 9
    COLUMN_COUNT = 10

    _HEADERS = [
        "Symbol", "N", "ATM", "Expiry",
        "Call Bid", "Call Ask", "C B/A",
        "Put Bid", "Put Ask", "P B/A",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tickers: list[TickerWatch] = []

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def add_ticker(self, ticker: TickerWatch) -> None:
        row = len(self._tickers)
        self.beginInsertRows(QModelIndex(), row, row)
        self._tickers.append(ticker)
        self.endInsertRows()

    def remove_row(self, row: int) -> TickerWatch | None:
        if not (0 <= row < len(self._tickers)):
            return None
        self.beginRemoveRows(QModelIndex(), row, row)
        ticker = self._tickers.pop(row)
        self.endRemoveRows()
        return ticker

    def get_ticker(self, row: int) -> TickerWatch | None:
        if 0 <= row < len(self._tickers):
            return self._tickers[row]
        return None

    def all_tickers(self) -> list[TickerWatch]:
        return list(self._tickers)

    def row_of(self, ticker: TickerWatch) -> int:
        try:
            return self._tickers.index(ticker)
        except ValueError:
            return -1

    def refresh_row(self, row: int) -> None:
        if 0 <= row < len(self._tickers):
            tl = self.index(row, 0)
            br = self.index(row, self.COLUMN_COUNT - 1)
            self.dataChanged.emit(tl, br)

    # ------------------------------------------------------------------
    # QAbstractTableModel
    # ------------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tickers)

    def columnCount(self, parent=QModelIndex()) -> int:
        return self.COLUMN_COUNT

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        ticker = self._tickers[index.row()]
        col = index.column()
        live = ticker.status == "Live"

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(ticker, col, live)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(ticker, col, live)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (self.COL_SYMBOL, self.COL_EXPIRY):
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and col == self.COL_SYMBOL:
            return ticker.status
        return None

    # ------------------------------------------------------------------
    # Cell rendering
    # ------------------------------------------------------------------

    def _display(self, t: TickerWatch, col: int, live: bool):
        if col == self.COL_SYMBOL:
            return t.underlying
        if col == self.COL_STRIKES:
            return str(t.num_strikes)
        if not live:
            # Show the status once (in ATM) and dashes elsewhere.
            if col == self.COL_ATM:
                return "…" if t.status == "Loading…" else "—"
            if col == self.COL_EXPIRY:
                return t.expiry or "—"
            return "—"
        if col == self.COL_ATM:
            return f"{t.atm_strike:g}" if t.atm_strike else "—"
        if col == self.COL_EXPIRY:
            return t.expiry or "—"
        if col == self.COL_CALL_BID:
            return _fmt_qty(t.call_bid)
        if col == self.COL_CALL_ASK:
            return _fmt_qty(t.call_ask)
        if col == self.COL_CALL_RATIO:
            return f"{t.call_ratio:.2f}" if t.call_ask else "—"
        if col == self.COL_PUT_BID:
            return _fmt_qty(t.put_bid)
        if col == self.COL_PUT_ASK:
            return _fmt_qty(t.put_ask)
        if col == self.COL_PUT_RATIO:
            return f"{t.put_ratio:.2f}" if t.put_ask else "—"
        return ""

    def _foreground(self, t: TickerWatch, col: int, live: bool):
        if not live:
            return _GREY
        if col in (self.COL_CALL_BID, self.COL_PUT_BID):
            return _GREEN
        if col in (self.COL_CALL_ASK, self.COL_PUT_ASK):
            return _RED
        if col == self.COL_CALL_RATIO:
            return _GREEN if t.call_ratio >= 1.0 else _RED
        if col == self.COL_PUT_RATIO:
            return _GREEN if t.put_ratio >= 1.0 else _RED
        return _WHITE
