"""QAbstractTableModel + two-row QHeaderView for the option chain table."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QHeaderView

from widgets.option_chain.option_chain_row import OptionChainRow


# ── Column definitions ────────────────────────────────────────────────────────

@dataclass
class ColumnDef:
    key: str
    label: str
    side: str       # "CE", "PE", or "CENTER"
    visible: bool = True
    width: int = 80


ALL_COLUMNS: list[ColumnDef] = [
    ColumnDef("ce_oi",      "OI",     "CE",     True,  90),
    ColumnDef("ce_oi_chg",  "OI Chg (L)", "CE",     True,  90),
    ColumnDef("ce_volume",  "Volume", "CE",     False, 80),
    ColumnDef("ce_iv",      "IV",     "CE",     True,  65),
    ColumnDef("ce_delta",   "Delta",  "CE",     False, 65),
    ColumnDef("ce_ltp",     "LTP",    "CE",     True,  80),
    ColumnDef("strike",     "Strike", "CENTER", True,  90),
    ColumnDef("pe_ltp",     "LTP",    "PE",     True,  80),
    ColumnDef("pe_delta",   "Delta",  "PE",     False, 65),
    ColumnDef("pe_iv",      "IV",     "PE",     True,  65),
    ColumnDef("pe_volume",  "Volume", "PE",     False, 80),
    ColumnDef("pe_oi_chg",  "OI Chg (L)", "PE",     True,  90),
    ColumnDef("pe_oi",      "OI",     "PE",     True,  90),
]

# Columns that cannot be hidden
_ALWAYS_VISIBLE = {"ce_ltp", "strike", "pe_ltp"}

# Colours
_CLR_TEXT      = QColor("#e6edf3")
_CLR_GREEN     = QColor("#3fb950")
_CLR_RED       = QColor("#f85149")
_CLR_AMBER     = QColor("#f0c040")
_CLR_CE_LTP    = QColor("#58a6ff")
_CLR_PE_LTP    = QColor("#ff7b72")
_CLR_MUTED     = QColor("#8b949e")

_BG_STANDARD   = QColor("#0d1117")
_BG_ATM        = QColor("#1f2937")
_BG_ITM_CE     = QColor("#0d1a0d")
_BG_ITM_PE     = QColor("#1a0d0d")


# ── Model ─────────────────────────────────────────────────────────────────────

class OptionChainModel(QAbstractTableModel):
    """Table model for one expiry's option chain.

    Live updates arrive via update_ce() / update_pe() / update_atm() —
    these emit dataChanged for only the affected cells, keeping repaints minimal.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[OptionChainRow] = []
        self._underlying_ltp: float = 0.0
        self._atm_strike: float = 0.0

        # Token → row-index lookup for O(1) updates
        self._ce_token_index: dict[str, int] = {}
        self._pe_token_index: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public column helpers
    # ------------------------------------------------------------------

    def visible_columns(self) -> list[ColumnDef]:
        return [c for c in ALL_COLUMNS if c.visible]

    def atm_row_index(self) -> int:
        for i, row in enumerate(self._rows):
            if row.is_atm:
                return i
        return 0

    # ------------------------------------------------------------------
    # Bulk update
    # ------------------------------------------------------------------

    def set_rows(self, rows: list[OptionChainRow], atm_strike: float) -> None:
        """Full reset — called on initial load or expiry change."""
        self.beginResetModel()
        self._rows = rows
        self._atm_strike = atm_strike
        self._underlying_ltp = 0.0  # will be updated by underlying tick

        self._ce_token_index = {r.ce_token: i for i, r in enumerate(rows) if r.ce_token}
        self._pe_token_index = {r.pe_token: i for i, r in enumerate(rows) if r.pe_token}

        for row in self._rows:
            row.is_atm = row.strike == atm_strike

        self.endResetModel()

    # ------------------------------------------------------------------
    # Incremental live updates
    # ------------------------------------------------------------------

    def update_ce(
        self,
        token: str,
        ltp: float,
        oi: int,
        oi_change: int,
        iv: float,
        delta: float,
        volume: int,
    ) -> None:
        row_idx = self._ce_token_index.get(token)
        if row_idx is None:
            return
        row = self._rows[row_idx]
        row.ce_ltp = ltp
        row.ce_oi = oi
        row.ce_oi_change = oi_change
        row.ce_iv = iv
        row.ce_delta = delta
        row.ce_volume = volume

        vis = self.visible_columns()
        ce_cols = [i for i, c in enumerate(vis) if c.side == "CE"]
        if ce_cols:
            self.dataChanged.emit(
                self.index(row_idx, ce_cols[0]),
                self.index(row_idx, ce_cols[-1]),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole],
            )

    def update_pe(
        self,
        token: str,
        ltp: float,
        oi: int,
        oi_change: int,
        iv: float,
        delta: float,
        volume: int,
    ) -> None:
        row_idx = self._pe_token_index.get(token)
        if row_idx is None:
            return
        row = self._rows[row_idx]
        row.pe_ltp = ltp
        row.pe_oi = oi
        row.pe_oi_change = oi_change
        row.pe_iv = iv
        row.pe_delta = delta
        row.pe_volume = volume

        vis = self.visible_columns()
        pe_cols = [i for i, c in enumerate(vis) if c.side == "PE"]
        if pe_cols:
            self.dataChanged.emit(
                self.index(row_idx, pe_cols[0]),
                self.index(row_idx, pe_cols[-1]),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole],
            )

    def update_atm(self, underlying_ltp: float) -> None:
        """Recompute ATM + ITM/OTM classification when underlying price changes."""
        self._underlying_ltp = underlying_ltp
        if not self._rows:
            return

        # Find closest strike
        new_atm = min(self._rows, key=lambda r: abs(r.strike - underlying_ltp)).strike
        changed = new_atm != self._atm_strike or True  # always refresh background
        self._atm_strike = new_atm

        for row in self._rows:
            row.is_atm = row.strike == new_atm

        if changed and self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, len(self.visible_columns()) - 1),
                [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.FontRole],
            )

    # ------------------------------------------------------------------
    # QAbstractTableModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.visible_columns())

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = self.visible_columns()[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(col, row)
        if role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(self._foreground(col, row))
        if role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(self._background(row))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(col)
        if role == Qt.ItemDataRole.FontRole:
            return self._font(col, row)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            cols = self.visible_columns()
            if 0 <= section < len(cols):
                return cols[section].label
        return None

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _display(self, col: ColumnDef, row: OptionChainRow) -> str:
        key = col.key
        if key == "ce_ltp":
            return f"{row.ce_ltp:.2f}" if row.ce_ltp else "—"
        if key == "ce_oi":
            return f"{row.ce_oi:,}" if row.ce_oi else "—"
        if key == "ce_oi_chg":
            if not row.ce_oi_change:
                return "—"
            v = row.ce_oi_change / 1_00_000
            return f"+{v:.2f}L" if row.ce_oi_change > 0 else f"{v:.2f}L"
        if key == "ce_iv":
            return f"{row.ce_iv:.2f}%" if row.ce_iv else "—"
        if key == "ce_delta":
            return f"{row.ce_delta:.3f}" if row.ce_delta else "—"
        if key == "ce_volume":
            return f"{row.ce_volume:,}" if row.ce_volume else "—"
        if key == "strike":
            return f"{row.strike:.0f}"
        if key == "pe_ltp":
            return f"{row.pe_ltp:.2f}" if row.pe_ltp else "—"
        if key == "pe_oi":
            return f"{row.pe_oi:,}" if row.pe_oi else "—"
        if key == "pe_oi_chg":
            if not row.pe_oi_change:
                return "—"
            v = row.pe_oi_change / 1_00_000
            return f"+{v:.2f}L" if row.pe_oi_change > 0 else f"{v:.2f}L"
        if key == "pe_iv":
            return f"{row.pe_iv:.2f}%" if row.pe_iv else "—"
        if key == "pe_delta":
            return f"{row.pe_delta:.3f}" if row.pe_delta else "—"
        if key == "pe_volume":
            return f"{row.pe_volume:,}" if row.pe_volume else "—"
        return ""

    def _foreground(self, col: ColumnDef, row: OptionChainRow) -> QColor:
        key = col.key
        if key == "ce_ltp":
            return _CLR_CE_LTP
        if key == "pe_ltp":
            return _CLR_PE_LTP
        if key == "strike":
            return _CLR_AMBER
        if key == "ce_oi_chg":
            if row.ce_oi_change > 0:
                return _CLR_GREEN
            if row.ce_oi_change < 0:
                return _CLR_RED
        if key == "pe_oi_chg":
            if row.pe_oi_change > 0:
                return _CLR_GREEN
            if row.pe_oi_change < 0:
                return _CLR_RED
        return _CLR_TEXT

    def _background(self, row: OptionChainRow) -> QColor:
        if row.is_atm:
            return _BG_ATM
        if self._underlying_ltp > 0:
            # ITM CE: strike < underlying (in-the-money for call)
            if row.strike < self._underlying_ltp:
                return _BG_ITM_CE
            # ITM PE: strike > underlying (in-the-money for put)
            if row.strike > self._underlying_ltp:
                return _BG_ITM_PE
        return _BG_STANDARD

    def _alignment(self, col: ColumnDef) -> Qt.AlignmentFlag:
        if col.side == "CE":
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if col.side == "PE":
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

    def _font(self, col: ColumnDef, row: OptionChainRow) -> QFont:
        font = QFont()
        if col.key == "strike":
            font.setBold(True)
            if row.is_atm:
                font.setPointSize(10)
        return font


# ── Two-row header ────────────────────────────────────────────────────────────

class OptionChainHeaderView(QHeaderView):
    """Custom horizontal header with a two-row layout.

    Top row:   CALLS (green, spanning all CE cols) | blank (CENTER) | PUTS (red, PE cols)
    Bottom row: individual column labels.
    """

    _ROW_HEIGHT = 22  # pixels per sub-row → total header height = 2 × this

    # Group styling
    _GRP = {
        "CE":     {"bg": QColor("#1a2a1a"), "fg": QColor("#3fb950"), "label": "CALLS"},
        "PE":     {"bg": QColor("#2a1a1a"), "fg": QColor("#f85149"), "label": "PUTS"},
        "CENTER": {"bg": QColor("#161b22"), "fg": QColor("#8b949e"), "label": ""},
    }
    _COL_LABEL_FG = QColor("#8b949e")
    _COL_LABEL_BG = QColor("#161b22")
    _BORDER        = QColor("#30363d")

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

    # Override to double the header height
    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        return QSize(base.width(), self._ROW_HEIGHT * 2)

    def paintSection(self, painter, rect: QRect, logical_index: int) -> None:
        if not rect.isValid():
            return

        model = self.model()
        if model is None or not hasattr(model, "visible_columns"):
            super().paintSection(painter, rect, logical_index)
            return

        vis = model.visible_columns()
        if logical_index >= len(vis):
            return

        col = vis[logical_index]
        grp = self._GRP[col.side]

        half = rect.height() // 2
        top_rect    = QRect(rect.x(), rect.y(), rect.width(), half)
        bottom_rect = QRect(rect.x(), rect.y() + half, rect.width(), rect.height() - half)

        painter.save()

        # ── Top half: group background ────────────────────────────────
        painter.fillRect(top_rect, grp["bg"])

        # Draw group label only on the first column of the group
        ce_cols  = [i for i, c in enumerate(vis) if c.side == "CE"]
        pe_cols  = [i for i, c in enumerate(vis) if c.side == "PE"]
        ctr_cols = [i for i, c in enumerate(vis) if c.side == "CENTER"]

        is_first_ce  = bool(ce_cols)  and ce_cols[0]  == logical_index
        is_first_pe  = bool(pe_cols)  and pe_cols[0]  == logical_index
        is_first_ctr = bool(ctr_cols) and ctr_cols[0] == logical_index

        if (is_first_ce or is_first_pe or is_first_ctr) and grp["label"]:
            # Compute full span width for centered text
            if col.side == "CE":
                span_width = sum(self.sectionSize(i) for i in ce_cols)
            elif col.side == "PE":
                span_width = sum(self.sectionSize(i) for i in pe_cols)
            else:
                span_width = sum(self.sectionSize(i) for i in ctr_cols)

            span_rect = QRect(top_rect.x(), top_rect.y(), span_width, top_rect.height())
            painter.setClipRect(span_rect)

            font = painter.font()
            font.setBold(True)
            font.setPointSize(9)
            painter.setFont(font)
            painter.setPen(grp["fg"])
            painter.drawText(span_rect, Qt.AlignmentFlag.AlignCenter, grp["label"])
            painter.setClipping(False)

        # ── Bottom half: column label ─────────────────────────────────
        painter.fillRect(bottom_rect, self._COL_LABEL_BG)

        font = painter.font()
        font.setBold(False)
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(self._COL_LABEL_FG)
        painter.drawText(
            bottom_rect.adjusted(2, 0, -2, 0),
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
            col.label,
        )

        # ── Borders ───────────────────────────────────────────────────
        painter.setPen(self._BORDER)
        # Divider between top and bottom rows
        painter.drawLine(top_rect.bottomLeft(), top_rect.bottomRight())
        # Right edge of section
        painter.drawLine(rect.topRight(), rect.bottomRight())

        painter.restore()
