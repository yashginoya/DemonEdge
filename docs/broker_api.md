# Broker API Reference

## Overview

All broker interactions go through `BaseBroker`. Never import `AngelBroker` or any concrete broker class outside of `broker/`.

## `BrokerAPIError` (`broker/base_broker.py`)

All broker implementations raise `BrokerAPIError` on failure. Callers catch this single type:

```python
from broker.base_broker import BrokerAPIError

try:
    broker.get_positions()
except BrokerAPIError as e:
    logger.error("Broker call failed: %s", e)
```

## BaseBroker Interface (`broker/base_broker.py`)

```python
class BaseBroker(ABC):
    # Identity — used by InstrumentMaster for cache file naming + download URL
    @property
    def broker_key(self) -> str: ...            # e.g. "angel"
    @property
    def instrument_master_url(self) -> str: ... # CDN URL, no auth required

    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def get_profile(self) -> dict: ...
    def get_holdings(self) -> list[Position]: ...
    def get_positions(self) -> list[Position]: ...
    def get_order_book(self) -> list[Order]: ...
    def place_order(self, instrument, side, order_type, quantity, price) -> str: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_ltp(self, exchange: str, token: str) -> float: ...
    def search_instruments(self, query: str) -> list[Instrument]: ...
    def get_historical_data(self, exchange, token, interval, from_date, to_date) -> list[dict]: ...
```

## BrokerManager (`broker/broker_manager.py`)

Singleton that holds the active broker instance.

```python
from broker.broker_manager import BrokerManager

# Preferred — factory creates, registers, and returns the broker:
credentials = {
    "api_key": "...",
    "client_id": "...",
    "password": "...",
    "totp_secret": "...",
}
broker = BrokerManager.create_broker("angel", credentials)

# In widgets and services (only way to access broker outside broker/):
broker = BrokerManager.get_broker()
positions = broker.get_positions()
```

`get_broker()` raises `RuntimeError("No broker set...")` if called before `set_broker()` / `create_broker()`.

### `create_broker(broker_name, credentials) -> BaseBroker`

Factory method. Currently supported: `"angel"`.

```python
BrokerManager.create_broker("angel", credentials)  # creates AngelBroker
BrokerManager.create_broker("unknown", {})           # raises ValueError
```

## AngelBroker (`broker/angel_broker.py`)

Wraps Angel SmartAPI (`SmartApi` package). Implements all `BaseBroker` abstract methods.

### Credentials dict

```python
{
    "api_key":     "YOUR_API_KEY",
    "client_id":   "YOUR_CLIENT_ID",
    "password":    "YOUR_PASSWORD",
    "totp_secret": "BASE32_TOTP_SECRET",
}
```

### Properties: `broker_key` and `instrument_master_url`

- `broker_key` → `"angel"` — used as the prefix for instrument master cache files.
- `instrument_master_url` → Angel CDN URL (public, no auth).  See `docs/instrument_master.md`.

### Additional method: `get_feed_token() -> str`

Returns the feed token received after `connect()`. Required by `MarketFeed` in Phase 4.

### `get_ltp` limitation

Angel's `ltpData` endpoint requires a trading symbol in addition to the token. The current implementation passes `token` as both arguments — this is a known limitation. Use `MarketFeed` (Phase 4) for real-time LTP in production.

### Historical data intervals

Pass Angel interval strings: `"ONE_MINUTE"`, `"THREE_MINUTE"`, `"FIVE_MINUTE"`, `"TEN_MINUTE"`, `"FIFTEEN_MINUTE"`, `"THIRTY_MINUTE"`, `"ONE_HOUR"`, `"ONE_DAY"`.

## Method Reference

| Method | Returns | Notes |
|---|---|---|
| `connect()` | `bool` | Authenticates, returns True on success |
| `disconnect()` | `None` | Closes session |
| `get_profile()` | `dict` | User profile from broker |
| `get_holdings()` | `list[Position]` | Equity holdings |
| `get_positions()` | `list[Position]` | Intraday/overnight positions |
| `get_order_book()` | `list[Order]` | All orders this session |
| `place_order(...)` | `str` | Returns order_id |
| `cancel_order(order_id)` | `bool` | True if accepted |
| `get_ltp(exchange, token)` | `float` | Last traded price (see limitation above) |
| `search_instruments(query)` | `list[Instrument]` | Uses local InstrumentMaster; falls back to live API if master not loaded |
| `get_historical_data(...)` | `list[dict]` | OHLCV list with keys: timestamp, open, high, low, close, volume |

## Rules

- Broker I/O calls must run in a worker thread (`QThreadPool` or `QThread`), never on the Qt main thread.
- Authentication/session renewal is handled inside the broker implementation.
- All errors from broker implementations are raised as `BrokerAPIError`.
- Never import `AngelBroker` outside of `broker/` — always use `BrokerManager.get_broker()`.
