"""Add / configure-ticker dialog for the Bid/Ask Quantity Watcher.

Collects an underlying symbol, an expiry (default nearest), and the number of
strikes per side.  In *edit* mode the underlying is fixed and only the expiry /
strikes can be changed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from utils.logger import get_logger
from widgets.option_chain import option_chain_builder as builder

logger = get_logger(__name__)

_QSS = """
QDialog { background: #0d1117; }
QLabel { color: #c9d1d9; font-size: 12px; }
QLabel#status { color: #8b949e; font-size: 11px; }
QLineEdit, QComboBox, QSpinBox {
    background: #161b22; border: 1px solid #30363d; border-radius: 4px;
    color: #e6edf3; padding: 5px 8px; font-size: 12px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #1f6feb; }
QComboBox QAbstractItemView {
    background: #161b22; color: #e6edf3; selection-background-color: #1f6feb;
}
QPushButton {
    background: #21262d; color: #e6edf3; border: 1px solid #30363d;
    border-radius: 4px; padding: 5px 12px;
}
QPushButton:hover { background: #30363d; }
"""

_COMPLETER_QSS = """
QListView {
    background: #161b22; color: #e6edf3; border: 1px solid #30363d;
    selection-background-color: #1f6feb; selection-color: #ffffff;
    outline: none;
}
"""


class AddTickerDialog(QDialog):
    """Emits ``config_selected(underlying, expiry, num_strikes)`` on accept."""

    config_selected = Signal(str, str, int)

    def __init__(
        self,
        parent: QWidget | None = None,
        underlying: str = "",
        expiry: str = "",
        num_strikes: int = 5,
        edit: bool = False,
    ) -> None:
        super().__init__(parent)
        self._edit = edit
        self._initial_expiry = expiry
        # display string ("NAME (BSE)") → (clean_name, fo_exchange)
        self._display_map: dict[str, tuple[str, str]] = {}
        self.setWindowTitle("Configure Symbol" if edit else "Add Symbol")
        self.setMinimumWidth(320)
        self.setModal(True)
        self.setStyleSheet(_QSS)

        self._build_ui(underlying, num_strikes)

        if underlying:
            self._underlying_input.setText(underlying.upper())
            self._load_expiries()
        if edit:
            self._underlying_input.setReadOnly(True)

    def _build_ui(self, underlying: str, num_strikes: int) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        # Underlying + Load
        u_row = QWidget()
        u_layout = QHBoxLayout(u_row)
        u_layout.setContentsMargins(0, 0, 0, 0)
        u_layout.setSpacing(6)
        self._underlying_input = QLineEdit()
        self._underlying_input.setPlaceholderText("e.g. NIFTY, BANKNIFTY, RELIANCE")
        self._underlying_input.returnPressed.connect(self._load_expiries)
        self._attach_completer()
        self._load_btn = QPushButton("Load")
        self._load_btn.clicked.connect(self._load_expiries)
        u_layout.addWidget(self._underlying_input, 1)
        u_layout.addWidget(self._load_btn)
        form.addRow("Underlying", u_row)

        # Expiry
        self._expiry_combo = QComboBox()
        self._expiry_combo.setEnabled(False)
        form.addRow("Expiry", self._expiry_combo)

        # Strikes per side
        self._strikes_spin = QSpinBox()
        self._strikes_spin.setRange(1, 20)
        self._strikes_spin.setValue(max(1, min(20, num_strikes)))
        form.addRow("Strikes per side", self._strikes_spin)

        outer.addLayout(form)

        self._status = QLabel("")
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save" if self._edit else "Add")
        self._buttons.accepted.connect(self._accept)
        self._buttons.rejected.connect(self.reject)
        self._ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        outer.addWidget(self._buttons)

        self._underlying_input.setFocus()

    def _attach_completer(self) -> None:
        """Suggest option-bearing underlyings (tagged NSE/BSE) as the user types."""
        from broker.instrument_master import InstrumentMaster
        if not InstrumentMaster.is_loaded():
            return
        pairs = InstrumentMaster.option_underlyings()  # [(name, fo_exchange)]
        if not pairs:
            return
        displays: list[str] = []
        for name, fo in pairs:
            cash = "BSE" if fo == "BFO" else "NSE"
            disp = f"{name} ({cash})"
            self._display_map[disp] = (name, fo)
            displays.append(disp)

        completer = QCompleter(displays, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setMaxVisibleItems(12)
        completer.popup().setStyleSheet(_COMPLETER_QSS)
        # When a suggestion is chosen, load its expiries right away.
        completer.activated.connect(lambda _t: QTimer.singleShot(0, self._load_expiries))
        self._underlying_input.setCompleter(completer)

    def _resolve_underlying(self) -> tuple[str, str]:
        """Return (clean_name, fo_exchange) from the input (tagged or raw)."""
        text = self._underlying_input.text().strip()
        if text in self._display_map:
            return self._display_map[text]
        name = text.upper()
        return name, (builder.get_option_exchange(name) or "NFO")

    # ------------------------------------------------------------------

    def _load_expiries(self) -> None:
        underlying, exchange = self._resolve_underlying()
        if not underlying:
            return

        from broker.instrument_master import InstrumentMaster
        if not InstrumentMaster.is_loaded():
            self._status.setText("Instrument master loading — please wait…")
            return

        expiries = builder.get_expiries(underlying, exchange)
        self._expiry_combo.clear()
        if not expiries:
            self._status.setText(f"No options found for '{underlying}'.")
            self._expiry_combo.setEnabled(False)
            self._ok_btn.setEnabled(False)
            return

        self._expiry_combo.addItems(expiries)
        self._expiry_combo.setEnabled(True)
        target = self._initial_expiry if self._initial_expiry in expiries else expiries[0]
        idx = self._expiry_combo.findText(target)
        if idx >= 0:
            self._expiry_combo.setCurrentIndex(idx)
        self._status.setText(f"{len(expiries)} expiries — nearest is {expiries[0]}.")
        self._ok_btn.setEnabled(True)

    def _accept(self) -> None:
        underlying, _exchange = self._resolve_underlying()
        expiry = self._expiry_combo.currentText()
        if not underlying or not expiry:
            return
        self.config_selected.emit(underlying, expiry, self._strikes_spin.value())
        self.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)
