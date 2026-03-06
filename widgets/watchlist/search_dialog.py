from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.instrument import Instrument
from utils.logger import get_logger

logger = get_logger(__name__)

_EXCHANGE_FILTERS = ["All", "NSE", "BSE", "NFO", "MCX"]


class SearchDialog(QDialog):
    """Instrument search popup — searches the local instrument master in-memory.

    Emits ``instrument_selected(Instrument)`` when the user confirms a choice.
    Usage::

        dlg = SearchDialog(parent)
        dlg.instrument_selected.connect(self._add_instrument)
        dlg.show()
    """

    instrument_selected = Signal(object)  # Instrument

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Instrument")
        self.setMinimumSize(500, 420)
        self.resize(500, 420)
        self.setModal(True)

        self._all_results: list[Instrument] = []

        # 400ms debounce — keeps the UI feel responsive even though search is synchronous
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._run_search)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # Search row
        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Type symbol or name (min 2 chars)…")
        self._search_input.textChanged.connect(self._on_text_changed)
        self._search_input.returnPressed.connect(self._accept_selected)

        self._exchange_filter = QComboBox()
        self._exchange_filter.addItems(_EXCHANGE_FILTERS)
        self._exchange_filter.setFixedWidth(70)
        self._exchange_filter.currentTextChanged.connect(self._apply_filter)

        search_layout.addWidget(self._search_input, 1)
        search_layout.addWidget(self._exchange_filter)

        # Results list
        self._result_list = QListWidget()
        self._result_list.setAlternatingRowColors(False)
        self._result_list.itemDoubleClicked.connect(self._accept_selected)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8b949e; font-size: 11px; padding: 2px 0;")

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add")
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)

        layout.addWidget(search_row)
        layout.addWidget(self._result_list, 1)
        layout.addWidget(self._status_label)
        layout.addWidget(buttons)

        self._result_list.currentItemChanged.connect(
            lambda cur, _: self._ok_btn.setEnabled(cur is not None)
        )

        self._search_input.setFocus()

    # ------------------------------------------------------------------
    # Search logic
    # ------------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        self._debounce_timer.stop()
        if len(text) >= 2:
            self._status_label.setText("Searching…")
            self._debounce_timer.start(400)
        else:
            self._result_list.clear()
            self._all_results = []
            self._status_label.setText("Type at least 2 characters")
            self._ok_btn.setEnabled(False)

    def _run_search(self) -> None:
        query = self._search_input.text().strip()
        if len(query) < 2:
            return

        from broker.instrument_master import InstrumentMaster
        im = InstrumentMaster

        if not im.is_loaded():
            self._status_label.setText("Instrument master loading — please wait…")
            return

        exchange = self._exchange_filter.currentText()
        exch_filter = "" if exchange == "All" else exchange

        results = im.search(query, exchange=exch_filter, max_results=200)
        self._all_results = results
        self._display_results(results)

    def _apply_filter(self, exchange: str) -> None:
        """Re-filter already-fetched results when exchange combo changes."""
        if not self._all_results:
            return
        if exchange == "All":
            filtered = self._all_results
        else:
            filtered = [i for i in self._all_results if i.exchange == exchange]
        self._display_results(filtered)

    def _display_results(self, instruments: list[Instrument]) -> None:
        self._result_list.clear()
        if not instruments:
            self._status_label.setText("No results found")
            self._ok_btn.setEnabled(False)
            return

        for inst in instruments:
            label = self._format_label(inst)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, inst)
            self._result_list.addItem(item)

        self._status_label.setText(f"{len(instruments)} result(s)")
        if self._result_list.count() > 0:
            self._result_list.setCurrentRow(0)

    @staticmethod
    def _format_label(inst: Instrument) -> str:
        """Build the display string shown in the results list."""
        base = f"{inst.symbol:<24}  {inst.exchange:<5}  {inst.instrument_type:<8}"
        if inst.expiry:
            return f"{base}  {inst.expiry:<12}  {inst.name}"
        return f"{base}  {inst.name}"

    # ------------------------------------------------------------------
    # Accept / emit
    # ------------------------------------------------------------------

    def _accept_selected(self) -> None:
        item = self._result_list.currentItem()
        if item is None:
            return
        instrument: Instrument = item.data(Qt.ItemDataRole.UserRole)
        self.instrument_selected.emit(instrument)
        self.accept()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._accept_selected()
        elif event.key() == Qt.Key.Key_Down:
            self._result_list.setFocus()
        else:
            super().keyPressEvent(event)
