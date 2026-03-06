from abc import abstractmethod
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QShowEvent
from PySide6.QtWidgets import QDockWidget, QWidget

from feed.feed_models import SubscriptionMode


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
    """

    # Emitted from closeEvent so MainWindow can clean up _active_widgets
    closed: Signal = Signal()

    widget_id: str = ""
    instance_id: str = ""  # set by MainWindow.spawn_widget()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        # Tracks subscriptions made via subscribe_feed() for auto-cleanup
        self._feed_subscriptions: list[tuple[str, str, Callable, int]] = []

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
