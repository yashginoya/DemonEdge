from __future__ import annotations

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from broker.broker_manager import BrokerManager
from feed.feed_models import SubscriptionMode
from models.instrument import Instrument
from utils.logger import get_logger
from widgets.base_widget import BaseWidget
from widgets.order_entry.order_form import OrderForm

logger = get_logger(__name__)


class _PlaceOrderWorker(QThread):
    """Places an order on a background thread."""

    succeeded = Signal(str)   # order_id
    failed    = Signal(str)   # error message

    def __init__(self, order_params: dict, parent=None) -> None:
        super().__init__(parent)
        self._params = order_params

    def run(self) -> None:
        try:
            order_id = BrokerManager.get_broker().place_order(self._params)
            self.succeeded.emit(order_id)
        except Exception as exc:
            self.failed.emit(str(exc))


_QSS = """
QWidget#order_entry_root {
    background: #0d1117;
}
QLabel#status_bar {
    background: #161b22;
    border-top: 1px solid #21262d;
    padding: 3px 8px;
    font-size: 11px;
    color: #8b949e;
}
"""


class OrderEntryWidget(BaseWidget):
    """Live order entry form.

    Supports MARKET / LIMIT / SL / SL-M order types, INTRADAY / DELIVERY
    product types, and NORMAL / BRACKET / COVER varieties.

    Emits ``order_placed(order_id)`` after a successful submission so
    ``MainWindow`` can trigger a Positions refresh.
    """

    widget_id = "order_entry"

    # Emitted after a successful order placement
    order_placed = Signal(str)  # order_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Order Entry", parent)
        self.setMinimumWidth(260)

        root = QWidget()
        root.setObjectName("order_entry_root")
        root.setStyleSheet(_QSS)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Form
        self._form = OrderForm()
        self._form.place_order_requested.connect(self._on_place_requested)
        self._form.instrument_changed.connect(self._on_instrument_changed)
        outer.addWidget(self._form, 1)

        # Status bar
        self._status = QLabel("")
        self._status.setObjectName("status_bar")
        self._status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(self._status)

        self.setWidget(root)

        # Auto-clear status after 10 s
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self._set_status("", ""))

        self._worker: _PlaceOrderWorker | None = None

    # ------------------------------------------------------------------
    # Public API (called by MainWindow / other widgets)
    # ------------------------------------------------------------------

    def set_instrument(self, instrument: Instrument) -> None:
        """Populate the form with the given instrument (from watchlist double-click)."""
        # Unsubscribe previous instrument
        self._unsubscribe_all_feeds()
        self._form.set_instrument(instrument)
        # Subscribe LTP for the new instrument
        self.subscribe_feed(
            instrument.exchange, instrument.token,
            self._form.ltp_feed_callback, SubscriptionMode.LTP
        )

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        # Re-subscribe current instrument if one is set
        inst = self._form.get_instrument()
        if inst:
            self.subscribe_feed(
                inst.exchange, inst.token,
                self._form.ltp_feed_callback, SubscriptionMode.LTP
            )

    def on_hide(self) -> None:
        pass  # _unsubscribe_all_feeds() is called automatically by BaseWidget

    def save_state(self) -> dict:
        return self._form.save_state()

    def restore_state(self, state: dict) -> None:
        self._form.restore_state(state)
        # Re-subscribe if an instrument was restored
        inst = self._form.get_instrument()
        if inst:
            self.subscribe_feed(
                inst.exchange, inst.token,
                self._form.ltp_feed_callback, SubscriptionMode.LTP
            )

    # ------------------------------------------------------------------
    # Instrument change
    # ------------------------------------------------------------------

    def _on_instrument_changed(self, instrument: Instrument) -> None:
        """Subscribe LTP when user picks a new instrument from the search dialog."""
        self._unsubscribe_all_feeds()
        self.subscribe_feed(
            instrument.exchange, instrument.token,
            self._form.ltp_feed_callback, SubscriptionMode.LTP
        )

    # ------------------------------------------------------------------
    # Order placement flow
    # ------------------------------------------------------------------

    def _on_place_requested(self, order_params: dict) -> None:
        """Show confirmation dialog, then place order in background thread."""
        from widgets.order_entry.order_confirmation_dialog import OrderConfirmationDialog
        from PySide6.QtWidgets import QDialog

        inst = self._form.get_instrument()
        if inst is None:
            return

        dlg = OrderConfirmationDialog(
            side=self._form.get_side(),
            quantity=int(order_params.get("quantity", 0)),
            symbol=inst.symbol,
            exchange=inst.exchange,
            order_type=self._form.get_display_order_type(),
            price=self._form.get_display_price(),
            product_type=self._form.get_display_product_type(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Disable button, show placing status
        self._form.set_place_btn_enabled(False)
        self._form.set_place_btn_text("Placing…")
        self._set_status("Placing order…", "#8b949e")

        # Run in background
        self._worker = _PlaceOrderWorker(order_params, self)
        self._worker.succeeded.connect(self._on_order_success)
        self._worker.failed.connect(self._on_order_failed)
        self._worker.start()

    def _on_order_success(self, order_id: str) -> None:
        self._form.set_place_btn_enabled(True)
        self._form.set_place_btn_text("PLACE ORDER")
        self._form.reset_quantity()
        self._form.show_error("")
        self._set_status(f"✓ Order placed — ID: {order_id}", "#3fb950")
        self._status_timer.start(10_000)
        self.order_placed.emit(order_id)
        logger.info("Order placed successfully: %s", order_id)

    def _on_order_failed(self, error: str) -> None:
        self._form.set_place_btn_enabled(True)
        self._form.set_place_btn_text("PLACE ORDER")
        self._set_status(f"✗ Failed: {error}", "#f85149")
        self._status_timer.start(10_000)
        logger.error("Order placement failed: %s", error)

    def _set_status(self, text: str, color: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(
            f"background:#161b22; border-top:1px solid #21262d;"
            f" padding:3px 8px; font-size:11px; color:{color or '#8b949e'};"
        )


# Self-register at import time
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=OrderEntryWidget.widget_id,
        display_name="Order Entry",
        category="Orders",
        factory=OrderEntryWidget,
    )
)
