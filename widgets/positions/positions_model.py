from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from models.position import Position

# Column indices
COL_SYMBOL    = 0
COL_EXCHANGE  = 1
COL_QTY       = 2
COL_AVG_PRICE = 3
COL_LTP       = 4
COL_UNREAL    = 5
COL_REAL      = 6
COL_TOTAL     = 7

_HEADERS = ["Symbol", "Exch", "Qty", "Avg Price", "LTP", "Unrealized P&L", "Realized P&L", "Total P&L"]

_PNL_COLUMNS = {COL_UNREAL, COL_REAL, COL_TOTAL}

_GREEN  = QColor("#3fb950")
_RED    = QColor("#f85149")
_MUTED  = QColor("#8b949e")
_TEXT   = QColor("#e6edf3")
_ROW_A  = QColor("#0d1117")
_ROW_B  = QColor("#161b22")

_MONO   = QFont("Courier New", 10)


def _pnl_color(val: float) -> QBrush:
    if val > 0:
        return QBrush(_GREEN)
    if val < 0:
        return QBrush(_RED)
    return QBrush(_MUTED)


class PositionsModel(QAbstractTableModel):
    """Table model for open positions with live LTP updates."""

    COLUMN_COUNT = len(_HEADERS)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[Position] = []

    # ------------------------------------------------------------------
    # QAbstractTableModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return self.COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, col)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col in _PNL_COLUMNS:
                val = self._pnl_val(row, col)
                return _pnl_color(val)
            return QBrush(_TEXT)

        if role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(_ROW_A if index.row() % 2 == 0 else _ROW_B)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_SYMBOL, COL_EXCHANGE):
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.FontRole:
            if col in (COL_AVG_PRICE, COL_LTP):
                return _MONO

        return None

    # ------------------------------------------------------------------
    # Public update API
    # ------------------------------------------------------------------

    def set_positions(self, positions: list[Position]) -> None:
        """Full data refresh — resets model."""
        self.beginResetModel()
        self._rows = list(positions)
        self.endResetModel()

    def update_ltp(self, token: str, ltp: float) -> int | None:
        """Update LTP for a token, recompute P&L. Returns row index or None."""
        for i, pos in enumerate(self._rows):
            if pos.token == token:
                pos.ltp = ltp
                pos.unrealized_pnl = (ltp - pos.average_price) * pos.quantity
                pos.total_pnl = pos.unrealized_pnl + pos.realized_pnl
                # Emit dataChanged for affected columns only
                tl = self.index(i, COL_LTP)
                br = self.index(i, COL_TOTAL)
                self.dataChanged.emit(tl, br, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole])
                return i
        return None

    def get_totals(self) -> tuple[float, float, float]:
        """Return (total_realized, total_unrealized, total_pnl)."""
        real    = sum(p.realized_pnl for p in self._rows)
        unreal  = sum(p.unrealized_pnl for p in self._rows)
        total   = sum(p.total_pnl for p in self._rows)
        return real, unreal, total

    def get_all_positions(self) -> list[Position]:
        return list(self._rows)

    def position_count(self) -> int:
        return len(self._rows)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _display(self, row: Position, col: int) -> str:
        if col == COL_SYMBOL:
            return row.symbol
        if col == COL_EXCHANGE:
            return row.exchange
        if col == COL_QTY:
            q = row.quantity
            return f"+{q}" if q > 0 else str(q)
        if col == COL_AVG_PRICE:
            return f"{row.average_price:.2f}"
        if col == COL_LTP:
            return f"{row.ltp:.2f}"
        if col == COL_UNREAL:
            return self._fmt_pnl(row.unrealized_pnl)
        if col == COL_REAL:
            return self._fmt_pnl(row.realized_pnl)
        if col == COL_TOTAL:
            return self._fmt_pnl(row.total_pnl)
        return ""

    def _pnl_val(self, row: Position, col: int) -> float:
        if col == COL_UNREAL:
            return row.unrealized_pnl
        if col == COL_REAL:
            return row.realized_pnl
        if col == COL_TOTAL:
            return row.total_pnl
        return 0.0

    @staticmethod
    def _fmt_pnl(val: float) -> str:
        if val > 0:
            return f"+{val:,.2f}"
        if val < 0:
            return f"{val:,.2f}"
        return "0.00"
