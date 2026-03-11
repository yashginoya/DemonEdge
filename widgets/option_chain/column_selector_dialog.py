"""Dialog for toggling option chain column visibility."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from widgets.option_chain.option_chain_model import ALL_COLUMNS, _ALWAYS_VISIBLE, ColumnDef

_QSS = """
QDialog {
    background: #0d1117;
    color: #e6edf3;
}
QListWidget {
    background: #161b22;
    border: 1px solid #30363d;
    color: #e6edf3;
    outline: none;
}
QListWidget::item:selected {
    background: #1f2937;
}
QListWidget::item:hover {
    background: #1f2937;
}
QPushButton {
    background: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 4px 12px;
}
QPushButton:hover {
    background: #30363d;
}
"""

# Column keys with their display group for the dialog
_SECTION_ORDER = ["CE", "CENTER", "PE"]
_SECTION_LABELS = {"CE": "CALLS", "CENTER": "CENTER", "PE": "PUTS"}
_SECTION_COLORS = {
    "CE":     "#3fb950",
    "CENTER": "#8b949e",
    "PE":     "#f85149",
}


class ColumnSelectorDialog(QDialog):
    """Modal dialog to toggle column visibility in the option chain.

    Emits ``columns_changed`` when the user applies changes.
    """

    columns_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Column Visibility")
        self.setMinimumWidth(280)
        self.setMinimumHeight(420)
        self.setStyleSheet(_QSS)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        self._list = QListWidget()
        self._list.setSpacing(2)
        layout.addWidget(self._list)

        # Buttons row
        btn_row = QHBoxLayout()
        self._reset_btn = QPushButton("Reset to Default")
        self._reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(self._apply_btn)
        layout.addLayout(btn_row)

        self._populate()

    def _populate(self) -> None:
        self._list.clear()
        for side in _SECTION_ORDER:
            # Section header
            header_item = QListWidgetItem(_SECTION_LABELS[side])
            font = QFont()
            font.setBold(True)
            font.setPointSize(9)
            header_item.setFont(font)
            header_item.setForeground(Qt.GlobalColor.transparent)  # will style via setData
            header_item.setData(Qt.ItemDataRole.ForegroundRole, __import__('PySide6.QtGui', fromlist=['QColor']).QColor(_SECTION_COLORS[side]))
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)  # non-interactive
            self._list.addItem(header_item)

            # Columns for this side (preserve order from ALL_COLUMNS)
            for col in ALL_COLUMNS:
                if col.side != side:
                    continue
                item = QListWidgetItem(f"  {col.label}")
                item.setData(Qt.ItemDataRole.UserRole, col.key)
                if col.key in _ALWAYS_VISIBLE:
                    item.setCheckState(Qt.CheckState.Checked)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                else:
                    item.setCheckState(
                        Qt.CheckState.Checked if col.visible else Qt.CheckState.Unchecked
                    )
                self._list.addItem(item)

    def _reset_defaults(self) -> None:
        """Restore default visibility from the initial ALL_COLUMNS definitions."""
        # Reset to hardcoded defaults (match the dataclass field defaults)
        _DEFAULTS = {
            "ce_oi": True, "ce_oi_chg": True, "ce_volume": False,
            "ce_iv": True, "ce_delta": False, "ce_ltp": True,
            "strike": True,
            "pe_ltp": True, "pe_delta": False, "pe_iv": True,
            "pe_volume": False, "pe_oi_chg": True, "pe_oi": True,
        }
        for i in range(self._list.count()):
            item = self._list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            if key and key not in _ALWAYS_VISIBLE:
                item.setCheckState(
                    Qt.CheckState.Checked if _DEFAULTS.get(key, True) else Qt.CheckState.Unchecked
                )

    def _apply(self) -> None:
        """Write checkbox state back to ALL_COLUMNS and emit columns_changed."""
        # Build a key → visible map from the list
        visibility: dict[str, bool] = {}
        for i in range(self._list.count()):
            item = self._list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            if key:
                visibility[key] = item.checkState() == Qt.CheckState.Checked

        for col in ALL_COLUMNS:
            if col.key in visibility:
                if col.key in _ALWAYS_VISIBLE:
                    col.visible = True
                else:
                    col.visible = visibility[col.key]

        self.columns_changed.emit()
        self.accept()
