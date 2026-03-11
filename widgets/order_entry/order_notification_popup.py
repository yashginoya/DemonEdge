"""Non-blocking toast notification for order placement results.

Appears bottom-right of the primary screen, stacks upward when multiple
popups are active.  Auto-dismisses after 5 s; also closes on click or
Enter/Escape.

Usage (class-level factory methods):
    OrderNotificationPopup.show_success(symbol, order_type, product_type,
                                        side, qty, price, order_id)
    OrderNotificationPopup.show_failure(symbol, error)
    OrderNotificationPopup.show_pending(symbol)
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Layout constants ──────────────────────────────────────────────────────────

_POPUP_WIDTH      = 330
_MARGIN_RIGHT     = 20
_MARGIN_BOTTOM    = 52   # clears the app status bar + typical Windows taskbar
_POPUP_GAP        = 8
_AUTO_DISMISS_MS  = 5_000

# ── Theme ─────────────────────────────────────────────────────────────────────

_ACCENT: dict[str, str] = {
    "success": "#3fb950",
    "failure": "#f85149",
    "pending": "#f0c040",
}

_TITLE: dict[str, str] = {
    "success": "Order Placed",
    "failure": "Order Rejected",
    "pending": "Order Pending",
}


# ── Popup widget ──────────────────────────────────────────────────────────────

class OrderNotificationPopup(QWidget):
    """Frameless toast notification widget.

    Do **not** instantiate directly — use the class-level factory methods:
    ``show_success``, ``show_failure``, ``show_pending``.
    """

    # Shared list of all currently visible popups (class-level, not instance)
    _active: ClassVar[list["OrderNotificationPopup"]] = []

    def __init__(
        self,
        status: str,          # "success" | "failure" | "pending"
        detail_lines: list[str],
    ) -> None:
        # Tool window: no taskbar entry, no title bar, always on top
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedWidth(_POPUP_WIDTH)

        accent = _ACCENT.get(status, "#8b949e")
        title  = _TITLE.get(status, "Order Notification")

        # ── Container (provides visible background + border) ──────────
        container = QWidget(self)
        container.setObjectName("toast_container")
        container.setStyleSheet(
            f"QWidget#toast_container {{"
            f"  background: #1c2128;"
            f"  border-top:    1px solid #30363d;"
            f"  border-right:  1px solid #30363d;"
            f"  border-bottom: 1px solid #30363d;"
            f"  border-left:   4px solid {accent};"
            f"  border-radius: 6px;"
            f"}}"
        )

        # Outer layout — just holds the container (margins create shadow room)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 8)   # extra bottom for shadow
        outer.addWidget(container)

        # Inner layout — the actual content
        inner = QVBoxLayout(container)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(5)

        # Title row
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {accent}; font-weight: bold; font-size: 12px; border: none;"
        )
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        # Small countdown hint
        self._timer_lbl = QLabel("5s")
        self._timer_lbl.setStyleSheet("color: #484f58; font-size: 10px; border: none;")
        title_row.addWidget(self._timer_lbl)

        inner.addLayout(title_row)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {accent}; opacity: 0.3;")
        inner.addWidget(sep)

        # Detail lines
        for line in detail_lines:
            lbl = QLabel(line)
            lbl.setStyleSheet("color: #e6edf3; font-size: 11px; border: none;")
            lbl.setWordWrap(True)
            inner.addWidget(lbl)

        # ── Drop shadow ────────────────────────────────────────────────
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        container.setGraphicsEffect(shadow)

        # ── Auto-dismiss timer ─────────────────────────────────────────
        self._remaining_s = _AUTO_DISMISS_MS // 1_000
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._dismiss)
        self._auto_timer.start(_AUTO_DISMISS_MS)

        # Countdown label update every second
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1_000)
        self._tick_timer.timeout.connect(self._tick_countdown)
        self._tick_timer.start()

        # ── Size + position ────────────────────────────────────────────
        self.adjustSize()
        self._position()

        # Register before show so _position of the NEXT popup can see us
        OrderNotificationPopup._active.append(self)

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _position(self) -> None:
        screen_geom = QApplication.primaryScreen().availableGeometry()
        x = screen_geom.right() - _POPUP_WIDTH - _MARGIN_RIGHT

        # Stack above existing active popups
        bottom_y = screen_geom.bottom() - _MARGIN_BOTTOM
        for popup in OrderNotificationPopup._active:
            # Use the top edge of each existing popup as the ceiling
            bottom_y = min(bottom_y, popup.y() - _POPUP_GAP)

        h = self.height() or 100
        self.move(x, bottom_y - h)

    # ------------------------------------------------------------------
    # Countdown
    # ------------------------------------------------------------------

    def _tick_countdown(self) -> None:
        self._remaining_s -= 1
        if self._remaining_s > 0:
            self._timer_lbl.setText(f"{self._remaining_s}s")
        else:
            self._tick_timer.stop()

    # ------------------------------------------------------------------
    # Dismiss
    # ------------------------------------------------------------------

    def _dismiss(self) -> None:
        self._auto_timer.stop()
        self._tick_timer.stop()
        self.close()

    # ------------------------------------------------------------------
    # Event overrides
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._dismiss()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self._dismiss()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self in OrderNotificationPopup._active:
            OrderNotificationPopup._active.remove(self)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Factory methods (public API)
    # ------------------------------------------------------------------

    @classmethod
    def show_success(
        cls,
        symbol: str,
        order_type: str,
        product_type: str,
        side: str,
        qty: int | str,
        price: float | str,
        order_id: str,
    ) -> "OrderNotificationPopup":
        """Show a green 'Order Placed' toast."""
        try:
            price_val = float(price)
            price_str = "MARKET" if price_val == 0.0 else f"₹{price_val:,.2f}"
        except (ValueError, TypeError):
            price_str = str(price)

        lines = [
            f"{side}  {symbol}",
            f"{order_type}  ·  {product_type}  ·  Qty: {qty}  ·  {price_str}",
            f"Order ID: {order_id}",
        ]
        popup = cls("success", lines)
        popup.show()
        logger.debug("OrderNotificationPopup: success shown for %s", symbol)
        return popup

    @classmethod
    def show_failure(
        cls,
        symbol: str,
        error: str,
    ) -> "OrderNotificationPopup":
        """Show a red 'Order Rejected' toast."""
        lines = [symbol, error]
        popup = cls("failure", lines)
        popup.show()
        logger.debug("OrderNotificationPopup: failure shown for %s: %s", symbol, error)
        return popup

    @classmethod
    def show_pending(cls, symbol: str) -> "OrderNotificationPopup":
        """Show an amber 'Order Pending' toast."""
        lines = [symbol, "Order pending broker confirmation."]
        popup = cls("pending", lines)
        popup.show()
        logger.debug("OrderNotificationPopup: pending shown for %s", symbol)
        return popup
