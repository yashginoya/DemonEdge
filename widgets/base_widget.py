from abc import abstractmethod
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent, QFont, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from feed.feed_models import SubscriptionMode

# ── Title bar QSS ─────────────────────────────────────────────────────────────
# Scoped to BaseWidgetTitleBar via setStyleSheet on the title bar widget itself,
# so the rules never leak into child content widgets.
_TITLEBAR_QSS = """
BaseWidgetTitleBar {
    background: #1f2937;
}
QPushButton {
    background: transparent;
    border: none;
    color: #8b949e;
    font-size: 13px;
    padding: 2px 6px;
    border-radius: 3px;
}
QPushButton#closeBtn:hover {
    background: #3a1a1a;
    color: #f85149;
}
QPushButton#floatBtn:hover {
    background: #1a2a3a;
    color: #1f6feb;
}
QPushButton#floatBtnActive {
    color: #1f6feb;
}
QPushButton#floatBtnActive:hover {
    background: #1a2a3a;
    color: #58a6ff;
}
"""


class BaseWidgetTitleBar(QWidget):
    """Custom title bar installed on every BaseWidget dock.

    Layout (left → right):
        [title label — stretches]  [⧉ float button]  [✕ close button]

    Signals
    -------
    close_clicked
        Emitted when the ✕ button is clicked.
    float_clicked
        Emitted when the ⧉ button is clicked.
    """

    close_clicked = Signal()
    float_clicked = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet(_TITLEBAR_QSS)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(2)

        # Title label
        self._title_label = QLabel(title)
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        self._title_label.setFont(font)
        self._title_label.setStyleSheet("color: #e6edf3; background: transparent;")
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._title_label)

        # Float / detach button
        self._float_btn = QPushButton("⧉")
        self._float_btn.setObjectName("floatBtn")
        self._float_btn.setFixedSize(20, 20)
        self._float_btn.setToolTip("Detach to floating window")
        self._float_btn.clicked.connect(self.float_clicked)
        layout.addWidget(self._float_btn)

        # Close button
        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setToolTip("Close widget")
        self._close_btn.clicked.connect(self.close_clicked)
        layout.addWidget(self._close_btn)

    # ------------------------------------------------------------------
    # Public helpers (called by BaseWidget on state changes)
    # ------------------------------------------------------------------

    def set_float_active(self, active: bool) -> None:
        """Highlight the float button when the widget is floating."""
        self._float_btn.setObjectName("floatBtnActive" if active else "floatBtn")
        # Force QSS re-evaluation after object name change
        self._float_btn.style().unpolish(self._float_btn)
        self._float_btn.style().polish(self._float_btn)

    def set_float_button_tooltip(self, tooltip: str) -> None:
        self._float_btn.setToolTip(tooltip)

    def update_title(self, title: str) -> None:
        self._title_label.setText(title)


class BaseWidget(QDockWidget):
    """Base class for all dockable widgets in the trading terminal.

    Subclasses must:
    - Set class attribute ``widget_id`` to a unique string.
    - Implement ``on_show()``, ``on_hide()``, ``save_state()``, ``restore_state()``.
    - Subscribe to MarketFeed in ``on_show()`` (or use ``subscribe_feed()`` for
      auto-managed subscriptions) and unsubscribe in ``on_hide()``.
    - Never reference concrete broker classes — only ``BrokerManager.get_broker()``.

    MainWindow sets ``instance_id`` after creation to allow multiple instances of the
    same widget type (e.g. two Watchlist widgets).

    Feed helper
    -----------
    Use ``self.subscribe_feed(exchange, token, callback, mode)`` instead of calling
    MarketFeed directly.  All subscriptions registered this way are automatically
    unsubscribed when the widget is hidden or closed — no need to touch ``on_hide()``.

    Title bar
    ---------
    Every widget automatically gets a custom title bar with a float (⧉) button and
    a close (✕) button.  No subclass action required — it is installed in
    ``__init__``.
    """

    # Emitted from closeEvent so MainWindow can clean up _active_widgets
    closed: Signal = Signal()

    widget_id: str = ""
    instance_id: str = ""  # set by MainWindow.spawn_widget()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)

        # Tracks subscriptions made via subscribe_feed() for auto-cleanup
        self._feed_subscriptions: list[tuple[str, str, Callable, int]] = []

        # Ensure all dock features are enabled
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        # Install custom title bar
        self._title_bar = BaseWidgetTitleBar(title=title, parent=self)
        self.setTitleBarWidget(self._title_bar)

        # Wire title bar buttons
        self._title_bar.close_clicked.connect(self.close)
        self._title_bar.float_clicked.connect(self._toggle_float)

        # Update float button appearance when floating state changes
        self.topLevelChanged.connect(self._on_float_state_changed)

    # ------------------------------------------------------------------
    # Abstract contract
    # ------------------------------------------------------------------

    @abstractmethod
    def on_show(self) -> None:
        """Called when widget becomes visible. Subscribe to feeds here."""
        ...

    @abstractmethod
    def on_hide(self) -> None:
        """Called when widget is hidden or closed. Unsubscribe from feeds here."""
        ...

    @abstractmethod
    def save_state(self) -> dict:
        """Return a JSON-serialisable dict representing widget state."""
        ...

    @abstractmethod
    def restore_state(self, state: dict) -> None:
        """Restore widget from a previously saved state dict."""
        ...

    # ------------------------------------------------------------------
    # Float / title bar helpers
    # ------------------------------------------------------------------

    def _toggle_float(self) -> None:
        self.setFloating(not self.isFloating())

    def _on_float_state_changed(self, floating: bool) -> None:
        if floating:
            self._title_bar.set_float_button_tooltip("Re-attach to main window")
            self._title_bar.set_float_active(True)
        else:
            self._title_bar.set_float_button_tooltip("Detach to floating window")
            self._title_bar.set_float_active(False)

    # ------------------------------------------------------------------
    # Feed helpers
    # ------------------------------------------------------------------

    def subscribe_feed(
        self,
        exchange: str,
        token: str,
        callback: Callable,
        mode: int = SubscriptionMode.LTP,
    ) -> None:
        """Subscribe to a market feed token and track it for auto-cleanup.

        All subscriptions registered via this method are automatically cancelled
        when the widget is hidden or closed, without any action needed in
        ``on_hide()``.

        Parameters
        ----------
        exchange:
            Exchange string e.g. ``"NSE"``, ``"NFO"``, ``"BSE"``, ``"MCX"``.
        token:
            Instrument token string (from Angel instrument master).
        callback:
            Callable with signature ``callback(tick: Tick)``.  Called on the
            feed thread — use a Qt signal to cross to the main thread.
        mode:
            :class:`~feed.feed_models.SubscriptionMode` value.
            Defaults to ``LTP``.
        """
        from feed.market_feed import MarketFeed

        MarketFeed.instance().subscribe(exchange, token, callback, mode)
        self._feed_subscriptions.append((exchange, token, callback, mode))

    def _unsubscribe_all_feeds(self) -> None:
        """Unsubscribe all subscriptions registered via ``subscribe_feed()``."""
        from feed.market_feed import MarketFeed

        feed = MarketFeed.instance()
        for exchange, token, callback, _mode in self._feed_subscriptions:
            feed.unsubscribe(exchange, token, callback)
        self._feed_subscriptions.clear()

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        self.on_show()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self.on_hide()
        self._unsubscribe_all_feeds()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.on_hide()
        self._unsubscribe_all_feeds()
        self.closed.emit()
        super().closeEvent(event)
