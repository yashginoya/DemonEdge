from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from models.instrument import Instrument
from models.tick import Tick
from utils.logger import get_logger

logger = get_logger(__name__)

# ── colours ──────────────────────────────────────────────────────────────────
_BUY_BG        = "#1a3a2a"
_BUY_FG        = "#3fb950"
_SELL_BG       = "#3a1a1a"
_SELL_FG       = "#f85149"
_BTN_BG        = "#21262d"
_BTN_FG        = "#e6edf3"
_BTN_BORDER    = "#30363d"
_ACTIVE_BG     = "#1f6feb22"
_ACTIVE_BORDER = "#1f6feb"
_FIELD_BG      = "#0d1117"
_FIELD_BORDER  = "#30363d"
_MUTED         = "#8b949e"
_ERROR_FG      = "#f85149"

_MARGIN_DEBOUNCE_MS = 600  # ms to wait after last field change before fetching


def _make_toggle_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setCheckable(True)
    btn.setFixedHeight(26)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return btn


def _toggle_group_style(active_bg: str, active_fg: str, active_border: str) -> str:
    return (
        f"QPushButton {{"
        f" background:{_BTN_BG}; color:{_MUTED}; border:1px solid {_BTN_BORDER};"
        f" border-radius:3px; font-size:11px; }}"
        f"QPushButton:checked {{"
        f" background:{active_bg}; color:{active_fg};"
        f" border:1px solid {active_border}; font-weight:bold; }}"
        f"QPushButton:hover:!checked {{ background:#30363d; color:{_BTN_FG}; }}"
    )


def _field_style() -> str:
    return (
        f"QDoubleSpinBox, QSpinBox {{"
        f" background:{_FIELD_BG}; color:{_BTN_FG};"
        f" border:1px solid {_FIELD_BORDER}; border-radius:3px;"
        f" padding:2px 4px; font-family:'Courier New',monospace; }}"
        f"QDoubleSpinBox:focus, QSpinBox:focus {{"
        f" border-color:{_ACTIVE_BORDER}; }}"
        f"QDoubleSpinBox:disabled, QSpinBox:disabled {{"
        f" color:{_MUTED}; background:#161b22; }}"
    )


# ── Margin fetch worker ───────────────────────────────────────────────────────

class _MarginWorker(QRunnable):
    """Fetches order margin estimate off the main thread."""

    class _Signals(QObject):
        done   = Signal(float)
        failed = Signal()

    def __init__(self, margin_params: dict) -> None:
        super().__init__()
        self.signals = _MarginWorker._Signals()
        self._params = margin_params

    def run(self) -> None:
        try:
            from broker.broker_manager import BrokerManager
            margin = BrokerManager.get_broker().get_order_margin(self._params)
            self.signals.done.emit(margin)
        except Exception as exc:
            logger.debug("Margin fetch failed: %s", exc)
            self.signals.failed.emit()


# ── Main form ─────────────────────────────────────────────────────────────────

class OrderForm(QWidget):
    """Embeddable order entry form (not a dialog).

    Signals
    -------
    place_order_requested
        Emitted with a validated order_params dict when the user clicks
        Place Order *and* validation passes.  Caller should show the
        confirmation dialog before actually submitting.
    instrument_changed(Instrument)
        Emitted whenever the user picks a new instrument.
    """

    place_order_requested = Signal(dict)    # validated order_params
    instrument_changed    = Signal(object)  # Instrument | None

    # Signal bridge: feed thread → main thread for LTP updates
    _ltp_signal = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._instrument: Instrument | None = None
        self._current_ltp: float = 0.0

        # 600ms debounce for margin fetch — single shared timer
        self._margin_timer = QTimer(self)
        self._margin_timer.setSingleShot(True)
        self._margin_timer.setInterval(_MARGIN_DEBOUNCE_MS)
        self._margin_timer.timeout.connect(self._start_margin_fetch)

        self._ltp_signal.connect(self._on_ltp_main)
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_instrument(self, instrument: Instrument) -> None:
        """Set the active instrument (called externally or from search dialog)."""
        self._instrument = instrument
        self._current_ltp = 0.0
        self._symbol_label.setText(f"{instrument.symbol}  |  {instrument.exchange}")
        self._symbol_label.setVisible(True)
        self._exchange_label.setText(instrument.exchange)
        self._ltp_value.setText("—")
        self._set_margin_text("Calculating…", _MUTED)
        self._schedule_margin_fetch()
        self.instrument_changed.emit(instrument)

    def get_instrument(self) -> Instrument | None:
        return self._instrument

    def get_order_params(self) -> dict:
        """Build the Angel SmartAPI placeOrder parameter dict from current form state."""
        inst = self._instrument
        if inst is None:
            return {}

        qty = self._qty_spin.value()
        price = (
            self._price_spin.value()
            if not self._price_spin.isHidden() and self._price_spin.isEnabled()
            else 0.0
        )
        trigger = self._trigger_spin.value() if not self._trigger_row.isHidden() else 0.0

        order_type   = self._get_selected(self._ot_group)
        product_type = self._get_selected(self._prod_group)
        variety      = self._get_selected(self._var_group)

        ot_map = {
            "MARKET": "MARKET",
            "LIMIT":  "LIMIT",
            "SL":     "STOPLOSS",
            "SL-M":   "STOPLOSS_MARKET",
        }
        variety_map = {
            "NORMAL":  "NORMAL",
            "BRACKET": "ROBO",
        }

        return {
            "variety":          variety_map.get(variety, "NORMAL"),
            "tradingsymbol":    inst.symbol,
            "symboltoken":      inst.token,
            "transactiontype":  self._side,
            "exchange":         inst.exchange,
            "ordertype":        ot_map.get(order_type, "MARKET"),
            "producttype":      product_type,
            "duration":         "DAY",
            "price":            str(price),
            "triggerprice":     str(trigger),
            "quantity":         str(qty),
            "squareflag":       True,
            "squareoff":        str(self._sq_spin.value()),
            "stoploss":         str(self._sl_spin.value()),
            "trailingStopLoss": str(self._tsl_spin.value()),
        }

    def reset_quantity(self) -> None:
        """Clear the quantity field (used after a successful order)."""
        self._qty_spin.setValue(0)

    def get_side(self) -> str:
        return self._side

    def get_display_price(self) -> float:
        """Return price for the confirmation dialog (0 for MARKET)."""
        if self._price_spin.isHidden() or not self._price_spin.isEnabled():
            return 0.0
        return self._price_spin.value()

    def get_display_order_type(self) -> str:
        ot = self._get_selected(self._ot_group)
        return {
            "MARKET": "MARKET",
            "LIMIT":  "LIMIT",
            "SL":     "STOPLOSS",
            "SL-M":   "STOPLOSS_MARKET",
        }.get(ot, ot)

    def get_display_product_type(self) -> str:
        return self._get_selected(self._prod_group)

    # Called by OrderEntryWidget (already on main thread via signal)
    def update_ltp(self, ltp: float) -> None:
        self._ltp_value.setText(f"₹{ltp:,.2f}")

    # Called from feed thread
    def ltp_feed_callback(self, tick: Tick) -> None:
        self._ltp_signal.emit(tick.ltp)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> str | None:
        """Return an error string if invalid, None if OK."""
        if self._instrument is None:
            return "No instrument selected"

        qty = self._qty_spin.value()
        if qty <= 0:
            return "Quantity must be greater than 0"

        order_type = self._get_selected(self._ot_group)
        if order_type in ("LIMIT", "SL") and self._price_spin.value() <= 0:
            return "Price must be greater than 0"

        if order_type in ("SL", "SL-M") and self._trigger_spin.value() <= 0:
            return "Trigger price must be greater than 0"

        variety = self._get_selected(self._var_group)
        if variety == "BRACKET":
            if self._sq_spin.value() <= 0:
                return "Squareoff must be greater than 0"
            if self._sl_spin.value() <= 0:
                return "Stoploss must be greater than 0"

        return None

    # ------------------------------------------------------------------
    # Margin fetch
    # ------------------------------------------------------------------

    def _get_margin_params(self) -> dict | None:
        """Build the margin params dict for Angel's margin/v1/batch API.

        The margin endpoint uses different field names from placeOrder:
        token, tradeType, productType (camelCase), qty (int), price (float).
        Only the fields the margin API actually needs are included.
        """
        inst = self._instrument
        if inst is None:
            return None
        qty = self._qty_spin.value()
        if qty <= 0:
            return None

        product_type = self._get_selected(self._prod_group)
        variety      = self._get_selected(self._var_group)

        # Bracket orders use "BO" as productType in the margin API
        margin_product_type = "BO" if variety == "BRACKET" else product_type

        if self._price_spin.isEnabled():
            price = self._price_spin.value()
        elif self._current_ltp > 0:
            # MARKET order — use current LTP as price estimate so the margin
            # calculator can compute a non-zero result (price × qty × rate)
            price = self._current_ltp
        else:
            price = 0.0

        return {
            "exchange":    inst.exchange,
            "token":       inst.token,
            "tradeType":   self._side,
            "productType": margin_product_type,
            "qty":         qty,
            "price":       price,
        }

    def _schedule_margin_fetch(self) -> None:
        """Reset the debounce timer — margin fetch fires after 600 ms of inactivity."""
        if self._instrument is None:
            self._set_margin_text("—", _MUTED)
            return
        self._margin_timer.start()  # restarts if already running

    def _start_margin_fetch(self) -> None:
        """Launch the margin worker (called by debounce timer on main thread)."""
        logger.debug("Margin fetch triggered")
        params = self._get_margin_params()
        if params is None:
            self._set_margin_text("—", _MUTED)
            return

        self._set_margin_text("Calculating…", _MUTED)
        worker = _MarginWorker(params)
        worker.signals.done.connect(self._on_margin_done)
        worker.signals.failed.connect(self._on_margin_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_margin_done(self, margin: float) -> None:
        if margin <= 0.0:
            self._set_margin_text("N/A", _MUTED)
        else:
            self._set_margin_text(f"₹{margin:,.2f}", _BTN_FG)

    def _on_margin_failed(self) -> None:
        self._set_margin_text("—", _MUTED)

    def _set_margin_text(self, text: str, color: str) -> None:
        self._margin_value.setText(text)
        self._margin_value.setStyleSheet(
            f"color:{color}; font-family:'Courier New',monospace; font-size:12px;"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_selected(self, group: QButtonGroup) -> str:
        btn = group.checkedButton()
        return btn.text() if btn else ""

    def _on_ltp_main(self, ltp: float) -> None:
        self._current_ltp = ltp
        self.update_ltp(ltp)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── BUY / SELL ─────────────────────────────────────────────────
        self._side = "BUY"
        side_row = QWidget()
        side_layout = QHBoxLayout(side_row)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(4)

        self._buy_btn = QPushButton("BUY")
        self._buy_btn.setCheckable(True)
        self._buy_btn.setChecked(True)
        self._buy_btn.setFixedHeight(36)
        self._buy_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._buy_btn.clicked.connect(lambda: self._set_side("BUY"))

        self._sell_btn = QPushButton("SELL")
        self._sell_btn.setCheckable(True)
        self._sell_btn.setFixedHeight(36)
        self._sell_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._sell_btn.clicked.connect(lambda: self._set_side("SELL"))

        side_layout.addWidget(self._buy_btn)
        side_layout.addWidget(self._sell_btn)
        root.addWidget(side_row)

        self._refresh_side_style()

        # ── Symbol ─────────────────────────────────────────────────────
        sym_row = QWidget()
        sym_layout = QHBoxLayout(sym_row)
        sym_layout.setContentsMargins(0, 0, 0, 0)
        sym_layout.setSpacing(6)

        sym_lbl = QLabel("Symbol:")
        sym_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        sym_lbl.setFixedWidth(54)

        self._symbol_btn = QPushButton("Click to select…")
        self._symbol_btn.setFixedHeight(26)
        self._symbol_btn.setStyleSheet(
            f"QPushButton {{ background:{_FIELD_BG}; color:{_MUTED};"
            f" border:1px solid {_FIELD_BORDER}; border-radius:3px;"
            f" text-align:left; padding:2px 6px; }}"
            f"QPushButton:hover {{ border-color:{_ACTIVE_BORDER}; color:{_BTN_FG}; }}"
        )
        self._symbol_btn.clicked.connect(self._open_search)

        self._symbol_label = QLabel("")
        self._symbol_label.setStyleSheet(
            f"color:{_BTN_FG}; font-size:11px; font-weight:bold;"
        )
        self._symbol_label.setVisible(False)

        sym_layout.addWidget(sym_lbl)
        sym_layout.addWidget(self._symbol_btn, 1)
        root.addWidget(sym_row)
        root.addWidget(self._symbol_label)

        self._exchange_label = QLabel("")  # internal, not shown

        # ── Divider ────────────────────────────────────────────────────
        root.addWidget(self._make_separator())

        # ── Order Type ─────────────────────────────────────────────────
        ot_row = QWidget()
        ot_layout = QHBoxLayout(ot_row)
        ot_layout.setContentsMargins(0, 0, 0, 0)
        ot_layout.setSpacing(4)

        ot_lbl = QLabel("Order:")
        ot_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        ot_lbl.setFixedWidth(54)
        ot_layout.addWidget(ot_lbl)

        self._ot_group = QButtonGroup(self)
        self._ot_group.setExclusive(True)
        ot_style = _toggle_group_style(_ACTIVE_BG, "#e6edf3", _ACTIVE_BORDER)

        for label in ("MARKET", "LIMIT", "SL", "SL-M"):
            btn = _make_toggle_btn(label)
            btn.setStyleSheet(ot_style)
            self._ot_group.addButton(btn)
            ot_layout.addWidget(btn)

        self._ot_group.buttons()[0].setChecked(True)
        self._ot_group.buttonClicked.connect(self._on_order_type_changed)
        root.addWidget(ot_row)

        # ── Product Type ───────────────────────────────────────────────
        prod_row = QWidget()
        prod_layout = QHBoxLayout(prod_row)
        prod_layout.setContentsMargins(0, 0, 0, 0)
        prod_layout.setSpacing(4)

        prod_lbl = QLabel("Product:")
        prod_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        prod_lbl.setFixedWidth(54)
        prod_layout.addWidget(prod_lbl)

        self._prod_group = QButtonGroup(self)
        self._prod_group.setExclusive(True)
        prod_style = _toggle_group_style(_ACTIVE_BG, "#e6edf3", _ACTIVE_BORDER)

        for label in ("INTRADAY", "DELIVERY"):
            btn = _make_toggle_btn(label)
            btn.setStyleSheet(prod_style)
            self._prod_group.addButton(btn)
            prod_layout.addWidget(btn)

        self._prod_group.buttons()[0].setChecked(True)
        self._prod_group.buttonClicked.connect(lambda _: self._schedule_margin_fetch())
        root.addWidget(prod_row)

        # ── Variety ────────────────────────────────────────────────────
        self._var_row = QWidget()
        var_layout = QHBoxLayout(self._var_row)
        var_layout.setContentsMargins(0, 0, 0, 0)
        var_layout.setSpacing(4)

        var_lbl = QLabel("Variety:")
        var_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        var_lbl.setFixedWidth(54)
        var_layout.addWidget(var_lbl)

        self._var_group = QButtonGroup(self)
        self._var_group.setExclusive(True)
        var_style = _toggle_group_style(_ACTIVE_BG, "#e6edf3", _ACTIVE_BORDER)

        for label in ("NORMAL", "BRACKET"):
            btn = _make_toggle_btn(label)
            btn.setStyleSheet(var_style)
            self._var_group.addButton(btn)
            var_layout.addWidget(btn)

        self._var_group.buttons()[0].setChecked(True)
        self._var_group.buttonClicked.connect(self._on_variety_changed)
        root.addWidget(self._var_row)

        # ── Divider ────────────────────────────────────────────────────
        root.addWidget(self._make_separator())

        # ── Qty / Price / Trigger ──────────────────────────────────────
        field_widget = QWidget()
        field_layout = QGridLayout(field_widget)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(4)
        field_style = _field_style()

        qty_lbl = QLabel("Qty:")
        qty_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        self._qty_spin = QSpinBox()
        self._qty_spin.setRange(0, 999999)
        self._qty_spin.setValue(0)
        self._qty_spin.setFixedHeight(28)
        self._qty_spin.setStyleSheet(field_style)
        self._qty_spin.valueChanged.connect(lambda _: self._schedule_margin_fetch())

        price_lbl = QLabel("Price:")
        price_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        self._price_spin = QDoubleSpinBox()
        self._price_spin.setRange(0.0, 9999999.0)
        self._price_spin.setDecimals(2)
        self._price_spin.setSingleStep(0.05)
        self._price_spin.setFixedHeight(28)
        self._price_spin.setStyleSheet(field_style)
        self._price_spin.setEnabled(False)  # starts disabled (MARKET)
        self._price_spin.valueChanged.connect(lambda _: self._schedule_margin_fetch())

        self._trigger_lbl = QLabel("Trigger:")
        self._trigger_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        self._trigger_spin = QDoubleSpinBox()
        self._trigger_spin.setRange(0.0, 9999999.0)
        self._trigger_spin.setDecimals(2)
        self._trigger_spin.setSingleStep(0.05)
        self._trigger_spin.setFixedHeight(28)
        self._trigger_spin.setStyleSheet(field_style)

        self._trigger_row = QWidget()
        tr_layout = QHBoxLayout(self._trigger_row)
        tr_layout.setContentsMargins(0, 0, 0, 0)
        tr_layout.setSpacing(4)
        tr_layout.addWidget(self._trigger_lbl)
        tr_layout.addWidget(self._trigger_spin)
        self._trigger_row.setVisible(False)

        field_layout.addWidget(qty_lbl, 0, 0)
        field_layout.addWidget(self._qty_spin, 0, 1)
        field_layout.addWidget(price_lbl, 1, 0)
        field_layout.addWidget(self._price_spin, 1, 1)
        root.addWidget(field_widget)
        root.addWidget(self._trigger_row)

        # ── Bracket fields ─────────────────────────────────────────────
        self._bracket_block = QWidget()
        brk_layout = QGridLayout(self._bracket_block)
        brk_layout.setContentsMargins(0, 0, 0, 0)
        brk_layout.setSpacing(4)

        for row_i, (label, attr) in enumerate([
            ("Squareoff:",   "_sq_spin"),
            ("Stoploss:",    "_sl_spin"),
            ("Trailing SL:", "_tsl_spin"),
        ]):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 9999999.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.05)
            spin.setFixedHeight(28)
            spin.setStyleSheet(field_style)
            setattr(self, attr, spin)
            brk_layout.addWidget(lbl, row_i, 0)
            brk_layout.addWidget(spin, row_i, 1)

        self._bracket_block.setVisible(False)
        root.addWidget(self._bracket_block)

        # ── Divider ────────────────────────────────────────────────────
        root.addWidget(self._make_separator())

        # ── LTP label ──────────────────────────────────────────────────
        ltp_row = QWidget()
        ltp_layout = QHBoxLayout(ltp_row)
        ltp_layout.setContentsMargins(0, 0, 0, 0)
        ltp_layout.setSpacing(6)

        ltp_key = QLabel("LTP:")
        ltp_key.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        ltp_key.setFixedWidth(72)
        self._ltp_value = QLabel("—")
        self._ltp_value.setStyleSheet(
            "color:#e6edf3; font-family:'Courier New',monospace;"
            " font-size:14px; font-weight:bold;"
        )
        ltp_layout.addWidget(ltp_key)
        ltp_layout.addWidget(self._ltp_value)
        ltp_layout.addStretch()
        root.addWidget(ltp_row)

        # ── Divider ────────────────────────────────────────────────────
        root.addWidget(self._make_separator())

        # ── Margin row ─────────────────────────────────────────────────
        margin_row = QWidget()
        margin_layout = QHBoxLayout(margin_row)
        margin_layout.setContentsMargins(0, 0, 0, 0)
        margin_layout.setSpacing(6)

        margin_key = QLabel("Margin:")
        margin_key.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        margin_key.setFixedWidth(72)
        self._margin_value = QLabel("—")
        self._margin_value.setStyleSheet(
            f"color:{_MUTED}; font-family:'Courier New',monospace; font-size:12px;"
        )
        margin_layout.addWidget(margin_key)
        margin_layout.addWidget(self._margin_value)
        margin_layout.addStretch()
        root.addWidget(margin_row)

        # ── Divider ────────────────────────────────────────────────────
        root.addWidget(self._make_separator())

        # ── Error label ────────────────────────────────────────────────
        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color:{_ERROR_FG}; font-size:11px;")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        root.addStretch()

        # ── Place Order button ─────────────────────────────────────────
        self._place_btn = QPushButton("PLACE ORDER")
        self._place_btn.setFixedHeight(40)
        self._place_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        self._place_btn.setFont(font)
        self._place_btn.clicked.connect(self._on_place_clicked)
        root.addWidget(self._place_btn)

        self._refresh_place_btn_style()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _set_side(self, side: str) -> None:
        self._side = side
        if side == "BUY":
            self._buy_btn.setChecked(True)
            self._sell_btn.setChecked(False)
        else:
            self._sell_btn.setChecked(True)
            self._buy_btn.setChecked(False)
        self._refresh_side_style()
        self._refresh_place_btn_style()
        self._schedule_margin_fetch()

    def _refresh_side_style(self) -> None:
        if self._side == "BUY":
            self._buy_btn.setStyleSheet(
                f"QPushButton {{ background:{_BUY_BG}; color:{_BUY_FG};"
                f" border:1px solid {_BUY_FG}; border-radius:3px;"
                f" font-weight:bold; font-size:13px; }}"
            )
            self._sell_btn.setStyleSheet(
                f"QPushButton {{ background:{_BTN_BG}; color:{_MUTED};"
                f" border:1px solid {_BTN_BORDER}; border-radius:3px; font-size:13px; }}"
                f"QPushButton:hover {{ background:#30363d; color:{_BTN_FG}; }}"
            )
        else:
            self._sell_btn.setStyleSheet(
                f"QPushButton {{ background:{_SELL_BG}; color:{_SELL_FG};"
                f" border:1px solid {_SELL_FG}; border-radius:3px;"
                f" font-weight:bold; font-size:13px; }}"
            )
            self._buy_btn.setStyleSheet(
                f"QPushButton {{ background:{_BTN_BG}; color:{_MUTED};"
                f" border:1px solid {_BTN_BORDER}; border-radius:3px; font-size:13px; }}"
                f"QPushButton:hover {{ background:#30363d; color:{_BTN_FG}; }}"
            )

    def _refresh_place_btn_style(self) -> None:
        if self._side == "BUY":
            bg, fg, border = _BUY_BG, _BUY_FG, _BUY_FG
        else:
            bg, fg, border = _SELL_BG, _SELL_FG, _SELL_FG
        self._place_btn.setStyleSheet(
            f"QPushButton {{ background:{bg}; color:{fg};"
            f" border:2px solid {border}; border-radius:4px; }}"
            f"QPushButton:hover {{ background:{bg.replace('1a', '2a')}; }}"
            f"QPushButton:pressed {{ background:{bg}; }}"
            f"QPushButton:disabled {{ background:#161b22; color:{_MUTED};"
            f" border-color:{_BTN_BORDER}; }}"
        )

    def _on_order_type_changed(self) -> None:
        ot = self._get_selected(self._ot_group)

        # ── Price field enable/disable ──────────────────────────────
        if ot in ("MARKET", "SL-M"):
            self._price_spin.setEnabled(False)
            self._price_spin.setValue(0.0)
        else:
            self._price_spin.setEnabled(True)
            # Pre-fill price with current LTP only if price is currently 0
            if self._current_ltp > 0 and self._price_spin.value() == 0.0:
                self._price_spin.setValue(self._current_ltp)

        # ── Trigger field show/hide ─────────────────────────────────
        show_trigger = ot in ("SL", "SL-M")
        self._trigger_row.setVisible(show_trigger)

        # Pre-fill trigger with LTP if trigger is currently 0
        if show_trigger and self._current_ltp > 0 and self._trigger_spin.value() == 0.0:
            self._trigger_spin.setValue(self._current_ltp)

        self._schedule_margin_fetch()

    def _on_variety_changed(self) -> None:
        variety = self._get_selected(self._var_group)
        self._bracket_block.setVisible(variety == "BRACKET")

        ot = self._get_selected(self._ot_group)
        self._trigger_row.setVisible(ot in ("SL", "SL-M"))

        self._schedule_margin_fetch()

    def _on_place_clicked(self) -> None:
        self._error_label.setText("")
        self._error_label.setVisible(False)

        error = self.validate()
        if error:
            self._error_label.setText(error)
            self._error_label.setVisible(True)
            return

        params = self.get_order_params()
        self.place_order_requested.emit(params)

    def _open_search(self) -> None:
        from widgets.watchlist.search_dialog import SearchDialog
        dlg = SearchDialog(self)
        dlg.instrument_selected.connect(self.set_instrument)
        dlg.exec()

    def show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.setVisible(bool(msg))

    def set_place_btn_enabled(self, enabled: bool) -> None:
        self._place_btn.setEnabled(enabled)

    def set_place_btn_text(self, text: str) -> None:
        self._place_btn.setText(text)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self) -> dict:
        state: dict = {
            "side":         self._side,
            "order_type":   self._get_selected(self._ot_group),
            "product_type": self._get_selected(self._prod_group),
            "variety":      self._get_selected(self._var_group),
        }
        if self._instrument:
            state["instrument"] = {
                "symbol":          self._instrument.symbol,
                "token":           self._instrument.token,
                "exchange":        self._instrument.exchange,
                "name":            self._instrument.name,
                "instrument_type": self._instrument.instrument_type,
            }
        return state

    def restore_state(self, state: dict) -> None:
        side = state.get("side", "BUY")
        self._set_side(side)

        ot = state.get("order_type", "MARKET")
        for btn in self._ot_group.buttons():
            if btn.text() == ot:
                btn.setChecked(True)
                break
        self._on_order_type_changed()

        pt = state.get("product_type", "INTRADAY")
        for btn in self._prod_group.buttons():
            if btn.text() == pt:
                btn.setChecked(True)
                break

        v = state.get("variety", "NORMAL")
        for btn in self._var_group.buttons():
            if btn.text() == v:
                btn.setChecked(True)
                break
        self._on_variety_changed()

        inst_data = state.get("instrument")
        if inst_data:
            try:
                inst = Instrument(**inst_data)
                self.set_instrument(inst)
            except Exception as exc:
                logger.warning("Failed to restore instrument: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #21262d; max-height: 1px;")
        return sep
