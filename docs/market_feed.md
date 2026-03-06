# MarketFeed Reference

## Overview

`MarketFeed` is a singleton managing the single Angel SmartWebSocketV2 WebSocket
connection for live tick data. Widgets never open their own connections.

## Starting the Feed

Call `MarketFeed.connect(broker)` after broker login succeeds.  This is done
automatically by `MainWindow.on_login_success()` — widgets don't need to call
it themselves.

```python
from feed.market_feed import MarketFeed
from broker.broker_manager import BrokerManager

MarketFeed.connect(BrokerManager.get_broker())
```

`connect()` returns immediately.  The WebSocket runs on a background daemon thread.
Listen to `MarketFeed.signals.feed_connected` to know when the feed is live.

## Subscribing to Ticks

**Recommended:** use `BaseWidget.subscribe_feed()` — subscriptions are tracked and
automatically cancelled when the widget is hidden or closed.

```python
class MyWidget(BaseWidget):
    _tick_signal = Signal(object)  # Tick

    def __init__(self, parent=None):
        super().__init__("My Widget", parent)
        self._tick_signal.connect(self._update_ui)

    def on_show(self) -> None:
        self.subscribe_feed("NSE", self._token, self._on_feed_tick)

    def on_hide(self) -> None:
        pass  # subscriptions auto-cancelled by BaseWidget

    def _on_feed_tick(self, tick) -> None:
        self._tick_signal.emit(tick)  # crosses to Qt main thread

    def _update_ui(self, tick) -> None:
        self._price_lbl.setText(f"{tick.ltp:.2f}")  # safe — main thread
```

**Manual:** call `MarketFeed.instance().subscribe()` / `unsubscribe()` directly
and manage cleanup yourself in `on_hide()`.

```python
from feed.market_feed import MarketFeed

MarketFeed.instance().subscribe("NSE", "1234", self._on_tick, mode=SubscriptionMode.QUOTE)
MarketFeed.instance().unsubscribe("NSE", "1234", self._on_tick)
```

## API

| Method | Signature | Description |
|---|---|---|
| `connect` | `(broker)` | Start WebSocket feed using broker credentials |
| `disconnect` | `()` | Close the WebSocket connection |
| `subscribe` | `(exchange, token, callback, mode=LTP)` | Register a callback for ticks |
| `unsubscribe` | `(exchange, token, callback)` | Remove a callback |
| `subscriber_count` | `()` | Total registered (key, callback) pairs |
| `is_connected` | property | True if WebSocket is currently connected |
| `signals` | property | `MarketFeedSignals` QObject (created lazily) |

## Signals (`feed/market_feed_signals.py`)

Connect to these from the main thread:

```python
from feed.market_feed import MarketFeed

MarketFeed.signals.feed_connected.connect(my_slot)
MarketFeed.signals.feed_disconnected.connect(my_slot)
MarketFeed.signals.feed_error.connect(lambda msg: print(msg))
MarketFeed.signals.tick_received.connect(debug_slot)  # every tick — high-frequency
```

| Signal | Args | Fired when |
|---|---|---|
| `feed_connected` | — | WebSocket handshake completes |
| `feed_disconnected` | — | WebSocket closes (graceful or unexpected) |
| `feed_error` | `str` | WebSocket error |
| `tick_received` | `Tick` | Every parsed tick — debug/status use only |

`signals` is lazy-initialised (QObject requires QApplication to exist first).

## Tick Data Model (`models/tick.py`)

```python
@dataclass
class Tick:
    token: str
    exchange_type: int          # ExchangeType int (1=NSE_CM, 2=NSE_FO, 3=BSE_CM, 4=BSE_FO, 5=MCX_FO)
    subscription_mode: int      # SubscriptionMode int
    sequence_number: int
    exchange_timestamp: datetime
    ltp: float                  # rupees (paise ÷ 100)

    # None in LTP mode; populated for QUOTE / SNAP_QUOTE:
    last_traded_quantity: int | None
    average_traded_price: float | None
    volume: int | None
    total_buy_quantity: float | None
    total_sell_quantity: float | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
```

All prices from the Angel feed are integers in paise — `MarketFeed._parse_tick()`
divides by 100 before constructing `Tick`.

## Feed Models (`feed/feed_models.py`)

```python
class SubscriptionMode(IntEnum):
    LTP = 1        # Last traded price only
    QUOTE = 2      # LTP + OHLCV + quantities
    SNAP_QUOTE = 3 # Full market depth snapshot
    DEPTH = 4      # Market depth only

class ExchangeType(IntEnum):
    NSE_CM = 1   # NSE Cash / Equity
    NSE_FO = 2   # NSE F&O
    BSE_CM = 3   # BSE Cash / Equity
    BSE_FO = 4   # BSE F&O
    MCX_FO = 5   # MCX Commodity F&O

exchange_str_to_type("NSE")  # → ExchangeType.NSE_CM (value 1)
exchange_type_to_str(2)      # → "NFO"
```

## Thread Safety

- `_subscribers` dict is protected by `threading.Lock`.
- Feed callbacks are invoked on the **daemon feed thread**.
- Widgets **must** emit a Qt signal to cross to the main thread — never update UI directly from a callback.
- `MarketFeedSignals` signals use Qt's queued connection automatically across threads.

## Internal Subscription Deduplication

MarketFeed tracks which `(exchange_type, token, mode)` combinations have been sent
to the WebSocket in `_ws_subscribed: set[str]`.  Duplicate `subscribe()` calls for the
same token+mode do not result in duplicate WebSocket messages, but each unique callback
still receives ticks.

## Reconnection

`SmartWebSocketV2` internally sets `RESUBSCRIBE_FLAG = True` after the first
`subscribe()` call.  On reconnect the library automatically calls `resubscribe()`
to restore all previously subscribed tokens — no application code needed.

New subscriptions added while the feed is disconnected are queued in `_pending`
and flushed when `_on_open` fires.
