from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

_GREEN = "#3fb950"
_RED   = "#f85149"
_MUTED = "#8b949e"
_TEXT  = "#e6edf3"


def _pnl_color(val: float) -> str:
    if val > 0:
        return _GREEN
    if val < 0:
        return _RED
    return _MUTED


def _fmt(val: float) -> str:
    if val > 0:
        return f"+₹{val:,.2f}"
    if val < 0:
        return f"-₹{abs(val):,.2f}"
    return "₹0.00"


def _label(text: str, color: str = _MUTED, bold: bool = False) -> QLabel:
    lbl = QLabel(text)
    style = f"color:{color}; font-size:11px;"
    if bold:
        style += " font-weight:bold;"
    lbl.setStyleSheet(style)
    return lbl


class PnLSummary(QFrame):
    """Compact P&L summary bar — sits above the positions/trades tab widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pnl_summary")
        self.setStyleSheet(
            "QFrame#pnl_summary {"
            " background: #161b22;"
            " border-bottom: 1px solid #21262d;"
            " padding: 2px 8px;"
            "}"
        )
        self.setFixedHeight(30)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(16)

        self._real_lbl   = QLabel("₹0.00")
        self._unreal_lbl = QLabel("₹0.00")
        self._total_lbl  = QLabel("₹0.00")
        self._count_lbl  = QLabel("0")

        for key_lbl, val_lbl in [
            ("Realized:", self._real_lbl),
            ("Unrealized:", self._unreal_lbl),
            ("Total:", self._total_lbl),
            ("Positions:", self._count_lbl),
        ]:
            layout.addWidget(_label(key_lbl))
            val_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px; font-weight:bold;")
            layout.addWidget(val_lbl)

        layout.addStretch()

    def update(self, realized: float, unrealized: float, total: float, count: int) -> None:  # type: ignore[override]
        """Refresh all displayed values."""
        self._real_lbl.setText(_fmt(realized))
        self._real_lbl.setStyleSheet(
            f"color:{_pnl_color(realized)}; font-size:11px; font-weight:bold;"
        )
        self._unreal_lbl.setText(_fmt(unrealized))
        self._unreal_lbl.setStyleSheet(
            f"color:{_pnl_color(unrealized)}; font-size:11px; font-weight:bold;"
        )
        self._total_lbl.setText(_fmt(total))
        self._total_lbl.setStyleSheet(
            f"color:{_pnl_color(total)}; font-size:11px; font-weight:bold;"
        )
        self._count_lbl.setText(str(count))
        self._count_lbl.setStyleSheet(f"color:{_TEXT}; font-size:11px; font-weight:bold;")
