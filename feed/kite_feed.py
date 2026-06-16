"""KiteFeed — Zerodha Kite WebSocket feed (concrete BaseFeed).

Wraps the official ``kiteconnect.KiteTicker``.  The ticker parses Kite's binary
protocol for us and hands ``on_ticks`` a list of dicts (prices already in
rupees, timestamps as ``datetime``); this class converts each into the app's
:class:`~models.tick.Tick` and dispatches to subscribers.

Singleton.  Selected as the active feed by ``FeedManager.create_feed("kite")``;
unlike AngelFeed it does NOT auto-register on import.

Threading
---------
``KiteTicker.connect(threaded=True)`` runs Twisted's reactor on a daemon thread,
so every callback (``on_ticks`` etc.) fires off the Qt main thread.  As with
AngelFeed, callbacks must marshal to the UI via Qt signals — never touch widgets
directly.  (The reactor is process-global and cannot be restarted once stopped,
so ``disconnect`` only closes the socket; it does not stop the reactor.)
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from feed.base_feed import BaseFeed
from feed.feed_models import SubscriptionMode
from models.tick import DepthLevel, Tick
from utils.logger import get_logger

if TYPE_CHECKING:
    from feed.market_feed_signals import MarketFeedSignals

logger = get_logger(__name__)

# Our SubscriptionMode → Kite mode string.
_MODE_TO_KITE = {
    SubscriptionMode.LTP: "ltp",
    SubscriptionMode.QUOTE: "quote",
    SubscriptionMode.SNAP_QUOTE: "full",
    SubscriptionMode.DEPTH: "full",
}
# Richness rank to pick the best mode when a token has several subscribers.
_MODE_RANK = {"ltp": 1, "quote": 2, "full": 3}
# Kite mode string → our SubscriptionMode int (for the Tick).
_KITE_TO_MODE = {
    "ltp": SubscriptionMode.LTP,
    "quote": SubscriptionMode.QUOTE,
    "full": SubscriptionMode.SNAP_QUOTE,
}


class KiteFeed(BaseFeed):
    """Zerodha Kite WebSocket feed."""

    _instance: "KiteFeed | None" = None

    def __new__(cls) -> "KiteFeed":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._subscribers: dict[str, list[Callable[[Tick], None]]] = {}
            inst._lock = threading.Lock()

            inst._ticker = None  # KiteTicker instance
            inst._is_connected = False

            # token(int) → richest Kite mode string currently desired
            inst._token_mode: dict[int, str] = {}
            # token(str) → exchange string (for building dispatch keys)
            inst._token_exchange: dict[str, str] = {}
            # tokens awaiting send until the socket connects
            inst._pending: set[int] = set()

            inst._signals: "MarketFeedSignals | None" = None
            cls._instance = inst
        return cls._instance

    @classmethod
    def instance(cls) -> "KiteFeed":
        return cls()

    # ------------------------------------------------------------------
    # Status / signals
    # ------------------------------------------------------------------

    @property
    def signals(self) -> "MarketFeedSignals":
        if self._signals is None:
            from feed.market_feed_signals import MarketFeedSignals
            self._signals = MarketFeedSignals()
        return self._signals

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self, broker) -> None:
        """Start the Kite WebSocket using *broker*'s api_key + access_token."""
        if self._ticker is not None:
            logger.warning("KiteFeed.connect() called while already connected")
            return

        from kiteconnect import KiteTicker

        ticker = KiteTicker(broker.api_key, broker.access_token)
        ticker.on_ticks = self._on_ticks
        ticker.on_connect = self._on_connect
        ticker.on_close = self._on_close
        ticker.on_error = self._on_error
        ticker.on_reconnect = self._on_reconnect
        ticker.on_noreconnect = self._on_noreconnect
        self._ticker = ticker

        ticker.connect(threaded=True)
        logger.info("KiteFeed: connecting to Kite WebSocket…")

    def disconnect(self) -> None:
        if self._ticker is not None:
            try:
                self._ticker.close()
            except Exception as exc:
                logger.warning("KiteFeed.disconnect() error (ignored): %s", exc)
        self._ticker = None
        self._is_connected = False
        self._pending.clear()
        logger.info("KiteFeed: disconnected")

    # ------------------------------------------------------------------
    # Pub / sub
    # ------------------------------------------------------------------

    def subscribe(
        self,
        exchange: str,
        token: str,
        callback: Callable[[Tick], None],
        mode: int = SubscriptionMode.LTP,
    ) -> None:
        key = f"{exchange}:{token}"
        with self._lock:
            self._subscribers.setdefault(key, [])
            if callback not in self._subscribers[key]:
                self._subscribers[key].append(callback)
            self._token_exchange[str(token)] = exchange

        kite_mode = _MODE_TO_KITE.get(mode, "ltp")
        try:
            itoken = int(token)
        except (TypeError, ValueError):
            logger.error("KiteFeed: non-numeric token %r", token)
            return

        # Keep the richest mode requested for this token.
        with self._lock:
            current = self._token_mode.get(itoken)
            if current is None or _MODE_RANK[kite_mode] > _MODE_RANK[current]:
                self._token_mode[itoken] = kite_mode
            desired_mode = self._token_mode[itoken]

        if self._is_connected and self._ticker is not None:
            self._send_subscribe(itoken, desired_mode)
        else:
            with self._lock:
                self._pending.add(itoken)
        logger.debug("KiteFeed subscribed: %s mode=%s", key, kite_mode)

    def unsubscribe(
        self,
        exchange: str,
        token: str,
        callback: Callable[[Tick], None],
    ) -> None:
        key = f"{exchange}:{token}"
        remaining = 0
        with self._lock:
            if key in self._subscribers:
                try:
                    self._subscribers[key].remove(callback)
                except ValueError:
                    pass
                remaining = len(self._subscribers[key])
                if remaining == 0:
                    del self._subscribers[key]

        if remaining == 0:
            try:
                itoken = int(token)
            except (TypeError, ValueError):
                return
            with self._lock:
                self._token_mode.pop(itoken, None)
                self._pending.discard(itoken)
            if self._is_connected and self._ticker is not None:
                try:
                    self._ticker.unsubscribe([itoken])
                except Exception as exc:
                    logger.warning("KiteFeed.unsubscribe send failed: %s", exc)
        logger.debug("KiteFeed unsubscribed: %s", key)

    def subscriber_count(self) -> int:
        with self._lock:
            return sum(len(cbs) for cbs in self._subscribers.values())

    # ------------------------------------------------------------------
    # KiteTicker callbacks — run on the Twisted reactor (feed) thread
    # ------------------------------------------------------------------

    def _on_connect(self, ws, response) -> None:
        self._is_connected = True
        logger.info("KiteFeed: WebSocket connected")
        # (Re)subscribe everything we know about — covers both first connect
        # and auto-reconnect.
        with self._lock:
            self._pending.clear()
            modes = dict(self._token_mode)
        by_mode: dict[str, list[int]] = {}
        for itoken, kmode in modes.items():
            by_mode.setdefault(kmode, []).append(itoken)
        for kmode, tokens in by_mode.items():
            self._send_subscribe_batch(tokens, kmode)
        self.signals.feed_connected.emit()

    def _on_ticks(self, ws, ticks: list) -> None:
        try:
            for raw in ticks:
                tick = self._parse_tick(raw)
                if tick is None:
                    continue
                self._dispatch(tick)
                self.signals.tick_received.emit(tick)
        except Exception:
            logger.exception("KiteFeed._on_ticks error")

    def _on_close(self, ws, code, reason) -> None:
        self._is_connected = False
        logger.info("KiteFeed: WebSocket closed (%s: %s)", code, reason)
        self.signals.feed_disconnected.emit()

    def _on_error(self, ws, code, reason) -> None:
        logger.error("KiteFeed WebSocket error (%s): %s", code, reason)
        self.signals.feed_error.emit(str(reason))

    def _on_reconnect(self, ws, attempts_count) -> None:
        logger.info("KiteFeed: reconnecting (attempt %s)…", attempts_count)

    def _on_noreconnect(self, ws) -> None:
        self._is_connected = False
        logger.error("KiteFeed: reconnection attempts exhausted")
        self.signals.feed_error.emit("Feed reconnection failed")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_subscribe(self, itoken: int, kite_mode: str) -> None:
        try:
            self._ticker.subscribe([itoken])
            self._ticker.set_mode(kite_mode, [itoken])
        except Exception as exc:
            logger.error("KiteFeed subscribe send failed for %s: %s", itoken, exc)

    def _send_subscribe_batch(self, tokens: list[int], kite_mode: str) -> None:
        if not tokens:
            return
        try:
            self._ticker.subscribe(tokens)
            self._ticker.set_mode(kite_mode, tokens)
        except Exception as exc:
            logger.error("KiteFeed batch subscribe failed (%s): %s", kite_mode, exc)

    def _parse_tick(self, data: dict) -> Tick | None:
        try:
            token = str(data.get("instrument_token", ""))
            mode_str = data.get("mode", "quote")
            sub_mode = int(_KITE_TO_MODE.get(mode_str, SubscriptionMode.QUOTE))

            ts = data.get("exchange_timestamp")
            exch_ts = ts if isinstance(ts, datetime) else datetime.now()

            with self._lock:
                exchange = self._token_exchange.get(token, "")
            exchange_type = _exchange_to_type(exchange)

            ohlc = data.get("ohlc") or {}

            depth = data.get("depth") or {}
            depth_buy = _parse_depth(depth.get("buy"))
            depth_sell = _parse_depth(depth.get("sell"))

            oi_raw = data.get("oi")
            oi = int(oi_raw) if oi_raw else None

            return Tick(
                token=token,
                exchange_type=exchange_type,
                subscription_mode=sub_mode,
                sequence_number=0,
                exchange_timestamp=exch_ts,
                ltp=_f(data.get("last_price")),
                last_traded_quantity=_opt_int(data.get("last_traded_quantity")),
                average_traded_price=_opt_f(data.get("average_traded_price")),
                volume=_opt_int(data.get("volume_traded")),
                total_buy_quantity=_opt_f(data.get("total_buy_quantity")),
                total_sell_quantity=_opt_f(data.get("total_sell_quantity")),
                open=_opt_f(ohlc.get("open")),
                high=_opt_f(ohlc.get("high")),
                low=_opt_f(ohlc.get("low")),
                close=_opt_f(ohlc.get("close")),
                open_interest=oi,
                depth_buy=depth_buy,
                depth_sell=depth_sell,
                last_traded_time=(
                    data.get("last_trade_time")
                    if isinstance(data.get("last_trade_time"), datetime)
                    else None
                ),
            )
        except Exception:
            logger.exception("KiteFeed._parse_tick failed for data: %s", data)
            return None

    def _dispatch(self, tick: Tick) -> None:
        with self._lock:
            exchange = self._token_exchange.get(tick.token, "")
        key = f"{exchange}:{tick.token}"
        with self._lock:
            callbacks = list(self._subscribers.get(key, []))
        for cb in callbacks:
            try:
                cb(tick)
            except Exception:
                logger.exception("Error in tick callback for %s", key)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _f(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _opt_f(val):
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _opt_int(val):
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_depth(levels) -> list[DepthLevel]:
    result: list[DepthLevel] = []
    for lvl in (levels or []):
        try:
            result.append(DepthLevel(
                price=_f(lvl.get("price")),
                quantity=int(lvl.get("quantity") or 0),
                orders=int(lvl.get("orders") or 0),
            ))
        except Exception:
            pass
    return result


def _exchange_to_type(exchange: str) -> int:
    """Best-effort map exchange string → app ExchangeType int (0 if unknown)."""
    from feed.feed_models import exchange_str_to_type
    try:
        return int(exchange_str_to_type(exchange))
    except ValueError:
        return 0
