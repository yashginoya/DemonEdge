from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from models.instrument import Instrument
from utils.logger import get_logger

logger = get_logger(__name__)

_EXCHANGES = ["NSE", "BSE", "NFO", "BFO", "MCX"]


class _LookupWorker(QRunnable):
    """Verifies a token exists via get_ltp() and returns the LTP."""

    class _Signals(QObject):
        done = Signal(float)
        error = Signal(str)

    def __init__(self, exchange: str, token: str) -> None:
        super().__init__()
        self.signals = _LookupWorker._Signals()
        self._exchange = exchange
        self._token = token

    def run(self) -> None:
        try:
            from broker.broker_manager import BrokerManager
            ltp = BrokerManager.get_broker().get_ltp(self._exchange, self._token)
            self.signals.done.emit(ltp)
        except Exception as exc:
            self.signals.error.emit(str(exc))


class AddManualDialog(QDialog):
    """Dialog for adding an instrument by entering exchange + token directly.

    Emits ``instrument_selected(Instrument)`` on confirm.
    """

    instrument_selected = Signal(object)  # Instrument

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add by Token")
        self.setFixedSize(320, 240)
        self.setModal(True)

        self._verified_ltp: float = 0.0
        self._lookup_done: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        self._exchange_cb = QComboBox()
        self._exchange_cb.addItems(_EXCHANGES)
        form.addRow("Exchange:", self._exchange_cb)

        self._token_input = QLineEdit()
        self._token_input.setPlaceholderText("Numeric token e.g. 2885")
        form.addRow("Token:", self._token_input)

        self._symbol_input = QLineEdit()
        self._symbol_input.setPlaceholderText("Optional display name")
        form.addRow("Symbol:", self._symbol_input)

        self._lookup_btn = QPushButton("Lookup")
        self._lookup_btn.clicked.connect(self._do_lookup)
        form.addRow("", self._lookup_btn)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        self._status_label.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)

        layout.addLayout(form)
        layout.addWidget(self._status_label)
        layout.addStretch()
        layout.addWidget(buttons)

        # Enable Add if symbol is manually filled even without lookup
        self._symbol_input.textChanged.connect(self._check_ok_state)
        self._token_input.textChanged.connect(lambda: setattr(self, "_lookup_done", False)
                                               or self._check_ok_state())

    def _check_ok_state(self) -> None:
        has_token = bool(self._token_input.text().strip())
        has_symbol = bool(self._symbol_input.text().strip())
        self._ok_btn.setEnabled(has_token and (has_symbol or self._lookup_done))

    def _do_lookup(self) -> None:
        token = self._token_input.text().strip()
        if not token:
            self._status_label.setText("Enter a token first.")
            return
        exchange = self._exchange_cb.currentText()
        self._status_label.setText(f"Looking up {exchange}:{token}…")
        self._lookup_btn.setEnabled(False)
        self._lookup_done = False

        worker = _LookupWorker(exchange, token)
        worker.signals.done.connect(self._on_lookup_done)
        worker.signals.error.connect(self._on_lookup_error)
        QThreadPool.globalInstance().start(worker)

    def _on_lookup_done(self, ltp: float) -> None:
        self._verified_ltp = ltp
        self._lookup_done = True
        self._lookup_btn.setEnabled(True)
        exchange = self._exchange_cb.currentText()
        token = self._token_input.text().strip()
        if not self._symbol_input.text().strip():
            self._symbol_input.setText(token)
        self._status_label.setText(f"Found: LTP = {ltp:.2f}")
        self._status_label.setStyleSheet("color: #3fb950; font-size: 11px;")
        self._check_ok_state()

    def _on_lookup_error(self, msg: str) -> None:
        self._lookup_done = False
        self._lookup_btn.setEnabled(True)
        self._status_label.setText(f"Lookup failed: {msg[:80]}")
        self._status_label.setStyleSheet("color: #f85149; font-size: 11px;")

    def _accept(self) -> None:
        token = self._token_input.text().strip()
        exchange = self._exchange_cb.currentText()
        symbol = self._symbol_input.text().strip() or token
        if not token:
            return
        instrument = Instrument(
            symbol=symbol,
            token=token,
            exchange=exchange,
            name=symbol,
            instrument_type="",
        )
        self.instrument_selected.emit(instrument)
        self.accept()
