from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from models.order import Order

# Column indices
COL_TIME    = 0
COL_SYMBOL  = 1
COL_SIDE    = 2
COL_QTY     = 3
COL_PRICE   = 4
COL_PRODUCT = 5
COL_STATUS  = 6

_HEADERS = ["Time", "Symbol", "Side", "Qty", "Price", "Product", "Status"]

_GREEN    = QColor("#3fb950")
_RED      = QColor("#f85149")
_AMBER    = QColor("#d29922")
_TEXT     = QColor("#e6edf3")
_MUTED    = QColor("#8b949e")
_ROW_A    = QColor("#0d1117")
_ROW_B    = QColor("#161b22")

_STATUS_COLOR: dict[str, QColor] = {
    "complete":   _GREEN,
    "rejected":   _RED,
    "cancelled":  _MUTED,
    "open":       _TEXT,
    "pending":    _AMBER,
}


class TradesModel(QAbstractTableModel):
    """Table model for today's order book entries (all statuses).

    Sorted newest-first.
    """

    COLUMN_COUNT = len(_HEADERS)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[Order] = []

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
            if col == COL_SIDE:
                return QBrush(_GREEN if row.side.upper() == "BUY" else _RED)
            if col == COL_STATUS:
                return QBrush(_STATUS_COLOR.get(row.status.lower(), _MUTED))
            return QBrush(_TEXT)

        if role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(_ROW_A if index.row() % 2 == 0 else _ROW_B)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_SYMBOL, COL_STATUS):
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None

    # ------------------------------------------------------------------
    # Public update API
    # ------------------------------------------------------------------

    def set_orders(self, orders: list[Order]) -> None:
        """Full refresh — replaces all rows, sorted newest-first."""
        self.beginResetModel()
        self._rows = sorted(orders, key=lambda o: o.timestamp, reverse=True)
        self.endResetModel()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _display(self, row: Order, col: int) -> str:
        if col == COL_TIME:
            return row.timestamp.strftime("%H:%M:%S")
        if col == COL_SYMBOL:
            return row.symbol
        if col == COL_SIDE:
            return row.side.upper()
        if col == COL_QTY:
            return str(row.quantity)
        if col == COL_PRICE:
            return f"{row.average_price:.2f}" if row.average_price else f"{row.price:.2f}"
        if col == COL_PRODUCT:
            return row.product_type
        if col == COL_STATUS:
            return row.status.upper()
        return ""
