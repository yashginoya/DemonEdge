from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from feed.feed_models import SubscriptionMode, exchange_str_to_type, exchange_type_to_str
from models.tick import Tick
from utils.logger import get_logger

if TYPE_CHECKING:
    from feed.market_feed_signals import MarketFeedSignals

logger = get_logger(__name__)


class _MarketFeed:
    """Singleton WebSocket feed manager with pub/sub interface.

    Usage
    -----
    After broker login, call ``MarketFeed.connect(broker)`` to start the feed.
    Widgets subscribe via ``MarketFeed.instance().subscribe(exchange, token, cb, mode)``
    and unsubscribe via ``MarketFeed.instance().unsubscribe(exchange, token, cb)``.

    Feed callbacks are invoked on the daemon feed thread.  Widgets must push data
    to the Qt main thread via Qt signals — never update UI directly from a callback.

    Signals
    -------
    ``MarketFeed.signals`` is a :class:`~feed.market_feed_signals.MarketFeedSignals`
    QObject.  Connect to it from the main thread to receive lifecycle events::

        MarketFeed.signals.feed_connected.connect(my_slot)
        MarketFeed.signals.feed_disconnected.connect(my_slot)
        MarketFeed.signals.feed_error.connect(my_error_slot)

    ``signals`` is created lazily (after QApplication exists).
    """

    _instance: "_MarketFeed | None" = None

    def __new__(cls) -> "_MarketFeed":
        if cls._instance is None:
            inst = super().__new__(cls)
            # Subscriber map: "EXCHANGE:token" → [callbacks]
            inst._subscribers: dict[str, list[Callable[[Tick], None]]] = {}
            inst._lock = threading.Lock()

            # WebSocket objects
            inst._sws = None  # SmartWebSocketV2 instance
            inst._feed_thread: threading.Thread | None = None
            inst._is_connected: bool = False

            # Subscriptions pending until WebSocket connects
            inst._pending: list[tuple[str, str, int]] = []  # (exchange, token, mode)
            # Tokens already sent to the WebSocket: "exchange_type:token:mode" set
            inst._ws_subscribed: set[str] = set()

            # Qt signal bridge — created lazily after QApplication exists
            inst._signals: "MarketFeedSignals | None" = None

            cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "_MarketFeed":
        return cls()

    @property
    def signals(self) -> "MarketFeedSignals":
        """Lazy-initialised Qt signal bridge.  QApplication must exist first."""
        if self._signals is None:
            from feed.market_feed_signals import MarketFeedSignals
            self._signals = MarketFeedSignals()
        return self._signals

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect(self, broker) -> None:
        """Start the WebSocket feed using credentials from *broker*.

        *broker* must expose ``auth_token``, ``api_key``, ``client_code``, and
        ``feed_token`` properties (as implemented by AngelBroker after connect).

        This method returns immediately — the WebSocket runs in a daemon thread.
        Listen to ``MarketFeed.signals.feed_connected`` to know when the feed is up.
        """
        if self._is_connected or self._feed_thread is not None:
            logger.warning("MarketFeed.connect() called while already connected/connecting")
            return

        auth_token = broker.auth_token
        api_key = broker.api_key
        client_code = broker.client_code
        feed_token = broker.feed_token

        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        self._sws = SmartWebSocketV2(auth_token, api_key, client_code, feed_token)
        self._sws.on_open = self._on_open
        self._sws.on_data = self._on_data
        self._sws.on_error = self._on_error
        self._sws.on_close = self._on_close

        self._feed_thread = threading.Thread(
            target=self._sws.connect,
            name="market-feed",
            daemon=True,
        )
        self._feed_thread.start()
        logger.info("MarketFeed: connecting to Angel WebSocket…")

    def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._sws is not None:
            try:
                self._sws.close_connection()
            except Exception as exc:
                logger.warning("MarketFeed.disconnect() error (ignored): %s", exc)
        self._sws = None
        self._feed_thread = None
        self._is_connected = False
        self._ws_subscribed.clear()
        logger.info("MarketFeed: disconnected")

    def subscribe(
        self,
        exchange: str,
        token: str,
        callback: Callable[[Tick], None],
        mode: int = SubscriptionMode.LTP,
    ) -> None:
        """Subscribe *callback* to tick updates for *exchange*:*token*.

        If the feed is connected the subscription is sent to the WebSocket
        immediately.  If not yet connected it is queued and sent once the feed
        establishes a connection.

        *mode* is a :class:`~feed.feed_models.SubscriptionMode` value.
        Callbacks are invoked on the **feed thread** — use Qt signals to cross
        to the main thread before updating UI.
        """
        key = f"{exchange}:{token}"
        with self._lock:
            if key not in self._subscribers:
                self._subscribers[key] = []
            if callback not in self._subscribers[key]:
                self._subscribers[key].append(callback)

        if self._is_connected and self._sws is not None:
            self._ws_subscribe(exchange, token, mode)
        else:
            pending_key = (exchange, token, mode)
            with self._lock:
                if pending_key not in self._pending:
                    self._pending.append(pending_key)

        logger.debug("MarketFeed subscribed: %s mode=%d", key, mode)

    def unsubscribe(
        self,
        exchange: str,
        token: str,
        callback: Callable[[Tick], None],
    ) -> None:
        """Remove *callback* from tick updates for *exchange*:*token*."""
        key = f"{exchange}:{token}"
        with self._lock:
            if key in self._subscribers:
                try:
                    self._subscribers[key].remove(callback)
                except ValueError:
                    pass
                if not self._subscribers[key]:
                    del self._subscribers[key]
        logger.debug("MarketFeed unsubscribed: %s", key)

    def subscriber_count(self) -> int:
        """Return the total number of (key, callback) registrations."""
        with self._lock:
            return sum(len(cbs) for cbs in self._subscribers.values())

    # ------------------------------------------------------------------
    # WebSocket callbacks — called from the feed daemon thread
    # ------------------------------------------------------------------

    def _on_open(self, wsapp) -> None:
        self._is_connected = True
        logger.info("MarketFeed: WebSocket connected")

        # Flush pending subscriptions accumulated before the feed started
        with self._lock:
            pending = list(self._pending)
            self._pending.clear()

        for exchange, token, mode in pending:
            self._ws_subscribe(exchange, token, mode)

        self.signals.feed_connected.emit()

    def _on_data(self, wsapp, data: dict) -> None:
        """Receive a parsed tick dict from SmartWebSocketV2 and dispatch it."""
        try:
            tick = self._parse_tick(data)
            if tick is None:
                return
            self._dispatch(tick)
            self.signals.tick_received.emit(tick)
        except Exception:
            logger.exception("MarketFeed._on_data error")

    def _on_error(self, *args) -> None:
        # SmartWebSocketV2 calls on_error(error_type_str, error_msg_str)
        error_msg = str(args[-1]) if args else "Unknown WebSocket error"
        logger.error("MarketFeed WebSocket error: %s", error_msg)
        self.signals.feed_error.emit(error_msg)

    def _on_close(self, wsapp) -> None:
        self._is_connected = False
        logger.info("MarketFeed: WebSocket closed")
        self.signals.feed_disconnected.emit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ws_subscribe(self, exchange: str, token: str, mode: int) -> None:
        """Send a single-token subscribe call to SmartWebSocketV2."""
        try:
            exchange_type = exchange_str_to_type(exchange).value
        except ValueError:
            logger.error("MarketFeed: unknown exchange for subscription: %s", exchange)
            return

        ws_key = f"{exchange_type}:{token}:{mode}"
        if ws_key in self._ws_subscribed:
            return  # already sent to WebSocket
        self._ws_subscribed.add(ws_key)

        token_list = [{"exchangeType": exchange_type, "tokens": [token]}]
        correlation_id = f"sub_{exchange}_{token}"
        try:
            self._sws.subscribe(correlation_id, mode, token_list)
            logger.debug("WS subscribe sent: %s token=%s mode=%d", exchange, token, mode)
        except Exception as exc:
            self._ws_subscribed.discard(ws_key)
            logger.error("MarketFeed._ws_subscribe failed: %s", exc)

    def _parse_tick(self, data: dict) -> Tick | None:
        """Parse SmartWebSocketV2 binary data dict into a :class:`~models.tick.Tick`.

        All prices from the feed are integers in paise — divide by 100 for rupees.
        ``exchange_timestamp`` is in milliseconds.
        """
        try:
            mode = int(data.get("subscription_mode", 1))
            exchange_type = int(data.get("exchange_type", 0))
            token = str(data.get("token", ""))
            sequence_number = int(data.get("sequence_number", 0))

            ts_ms = data.get("exchange_timestamp", 0)
            exchange_timestamp = datetime.fromtimestamp(int(ts_ms) / 1000)

            ltp = int(data.get("last_traded_price", 0)) / 100.0

            # Optional QUOTE / SNAP_QUOTE fields
            ltq = atp = volume = tbq = tsq = open_p = high_p = low_p = close_p = None

            # closed_price (previous day's close) is sent in all subscription modes
            # by Angel One — parse it unconditionally so LTP-mode subscribers can use
            # it for CHANGE / CHG% calculations.
            _close_raw = int(data.get("closed_price", 0))
            close_p = _close_raw / 100.0 if _close_raw > 0 else None

            if mode in (SubscriptionMode.QUOTE, SubscriptionMode.SNAP_QUOTE):
                ltq = int(data.get("last_traded_quantity", 0))
                atp = int(data.get("average_traded_price", 0)) / 100.0
                volume = int(data.get("volume_trade_for_the_day", 0))
                tbq = float(data.get("total_buy_quantity", 0))
                tsq = float(data.get("total_sell_quantity", 0))
                open_p = int(data.get("open_price_of_the_day", 0)) / 100.0
                high_p = int(data.get("high_price_of_the_day", 0)) / 100.0
                low_p = int(data.get("low_price_of_the_day", 0)) / 100.0
                # close_p already parsed above

            return Tick(
                token=token,
                exchange_type=exchange_type,
                subscription_mode=mode,
                sequence_number=sequence_number,
                exchange_timestamp=exchange_timestamp,
                ltp=ltp,
                last_traded_quantity=ltq,
                average_traded_price=atp,
                volume=volume,
                total_buy_quantity=tbq,
                total_sell_quantity=tsq,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
            )
        except Exception:
            logger.exception("MarketFeed._parse_tick failed for data: %s", data)
            return None

    def _dispatch(self, tick: Tick) -> None:
        """Dispatch a tick to all registered callbacks (runs on feed thread)."""
        exchange_str = exchange_type_to_str(tick.exchange_type)
        key = f"{exchange_str}:{tick.token}"
        with self._lock:
            callbacks = list(self._subscribers.get(key, []))
        for cb in callbacks:
            try:
                cb(tick)
            except Exception:
                logger.exception("Error in tick callback for %s", key)


MarketFeed = _MarketFeed()
