from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from models.instrument import Instrument
from models.tick import Tick
from widgets.watchlist.watchlist_row import WatchlistRow

_GREEN = QColor("#3fb950")
_RED = QColor("#f85149")
_MUTED = QColor("#8b949e")
_BG_EVEN = QColor("#0d1117")
_BG_ODD = QColor("#161b22")
_BG_FLASH_UP = QColor("#1a3a2a")
_BG_FLASH_DOWN = QColor("#3a1a1a")

_LTP_FONT = QFont()
_LTP_FONT.setBold(True)


class WatchlistModel(QAbstractTableModel):
    """Table model backing a single watchlist tab.

    Thread safety: all methods must be called from the Qt main thread except
    ``update_tick`` which is called from ``_on_tick_ui`` (already on main thread
    via Qt signal delivery).
    """

    COL_SYMBOL = 0
    COL_EXCHANGE = 1
    COL_LTP = 2
    COL_CHANGE = 3
    COL_CHANGE_PCT = 4
    COLUMN_COUNT = 5
    COLUMN_HEADERS = ["Symbol", "Exch", "LTP", "Change", "Chg%"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[WatchlistRow] = []

    # ------------------------------------------------------------------
    # QAbstractTableModel overrides
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows) if not parent.isValid() else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return self.COLUMN_COUNT if not parent.isValid() else 0

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMN_HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None

        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, col)

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(row, col)

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background(row, index.row())

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (self.COL_LTP, self.COL_CHANGE, self.COL_CHANGE_PCT):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.FontRole and col == self.COL_LTP:
            return _LTP_FONT

        return None

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _display(self, row: WatchlistRow, col: int):
        if col == self.COL_SYMBOL:
            return row.instrument.symbol
        if col == self.COL_EXCHANGE:
            return row.instrument.exchange
        if col == self.COL_LTP:
            return f"{row.ltp:.2f}" if row.ltp else "—"
        if col == self.COL_CHANGE:
            if row.prev_close == 0:
                return "-"
            return f"+{row.change:.2f}" if row.change >= 0 else f"{row.change:.2f}"
        if col == self.COL_CHANGE_PCT:
            if row.prev_close == 0:
                return "-"
            return f"+{row.change_pct:.2f}%" if row.change_pct >= 0 else f"{row.change_pct:.2f}%"
        return None

    def _foreground(self, row: WatchlistRow, col: int):
        if col not in (self.COL_CHANGE, self.COL_CHANGE_PCT):
            return None
        if row.prev_close == 0:
            return _MUTED
        if row.change > 0:
            return _GREEN
        if row.change < 0:
            return _RED
        return _MUTED

    def _background(self, row: WatchlistRow, row_index: int):
        if row.flash_counter > 0:
            return _BG_FLASH_UP if row.last_tick_direction > 0 else _BG_FLASH_DOWN
        return _BG_EVEN if row_index % 2 == 0 else _BG_ODD

    # ------------------------------------------------------------------
    # Live update methods
    # ------------------------------------------------------------------

    def update_tick(self, token: str, tick: Tick) -> int:
        """Update LTP from a live tick. Returns row index, or -1 if not found.

        Must be called from the Qt main thread (via signal delivery).
        """
        for i, row in enumerate(self._rows):
            if row.instrument.token == token:
                old_ltp = row.ltp
                row.ltp = tick.ltp
                if row.prev_close > 0:
                    row.change = tick.ltp - row.prev_close
                    row.change_pct = (row.change / row.prev_close) * 100

                if tick.ltp > old_ltp:
                    row.last_tick_direction = 1
                elif tick.ltp < old_ltp:
                    row.last_tick_direction = -1

                row.flash_counter = 3

                tl = self.index(i, 0)
                br = self.index(i, self.COLUMN_COUNT - 1)
                self.dataChanged.emit(tl, br, [Qt.ItemDataRole.DisplayRole,
                                               Qt.ItemDataRole.ForegroundRole,
                                               Qt.ItemDataRole.BackgroundRole])
                return i
        return -1

    def update_initial_ltp(self, token: str, ltp: float) -> None:
        """Set initial LTP and prev_close from a REST fetch.

        Sets both so change shows '0.00' (flat) immediately after add,
        then updates properly as ticks arrive.
        """
        for i, row in enumerate(self._rows):
            if row.instrument.token == token:
                row.ltp = ltp
                row.prev_close = ltp
                row.change = 0.0
                row.change_pct = 0.0
                tl = self.index(i, 0)
                br = self.index(i, self.COLUMN_COUNT - 1)
                self.dataChanged.emit(tl, br)
                return

    def tick_flash_step(self) -> list[int]:
        """Decrement flash counters; return list of row indices that changed."""
        changed: list[int] = []
        for i, row in enumerate(self._rows):
            if row.flash_counter > 0:
                row.flash_counter -= 1
                changed.append(i)
        return changed

    # ------------------------------------------------------------------
    # Structural changes
    # ------------------------------------------------------------------

    def add_instrument(self, instrument: Instrument) -> bool:
        """Append instrument. Returns False if already present (by token)."""
        for row in self._rows:
            if row.instrument.token == instrument.token:
                return False
        pos = len(self._rows)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self._rows.append(WatchlistRow(instrument=instrument))
        self.endInsertRows()
        return True

    def remove_instrument(self, row_index: int) -> Instrument:
        """Remove row and return its Instrument (for unsubscription)."""
        instrument = self._rows[row_index].instrument
        self.beginRemoveRows(QModelIndex(), row_index, row_index)
        self._rows.pop(row_index)
        self.endRemoveRows()
        return instrument

    def get_all_instruments(self) -> list[Instrument]:
        return [row.instrument for row in self._rows]

    def get_row(self, index: int) -> WatchlistRow:
        return self._rows[index]
