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

## Broker Implementations

| Key | Class | Auth |
|---|---|---|
| `angel` | `broker/angel_broker.py` `AngelBroker` | TOTP (api_key + client_id + password + totp_secret) |
| `kite` | `broker/kite_broker.py` `KiteBroker` | OAuth redirect (api_key + api_secret → request_token → access_token) |

`BrokerManager.create_broker(broker_key, credentials)` instantiates and registers
the named broker. Both can be configured simultaneously; the login dialog selects
which is active.

### `KiteBroker` notes
- Wraps the official `kiteconnect.KiteConnect`. `connect()` exchanges a
  `request_token` (set via `set_request_token()`) for a daily `access_token`, or
  validates a cached token. The interactive browser/redirect-capture lives in
  `broker/kite_auth.py`; `KiteBroker` never opens a browser itself.
- Exposes `api_key` / `access_token` / `access_token_date` (for the feed and
  same-day token caching) and `login_url()`.
- Translates the app's Angel-style order/margin param dicts into Kite's call
  signature (variety as an argument, MIS/CNC/NRML product chosen by segment,
  SL/SL-M order types, `minute`/`day` intervals). Bracket/ROBO orders are
  unsupported on Kite and downgraded to a regular order.

## `fetch_instruments()` — canonical instrument schema

`BaseBroker.fetch_instruments() -> list[dict]` downloads the broker's full
instrument dump and maps it into a **broker-neutral canonical schema** that
`InstrumentMaster` caches and indexes. Each record:

| key | type | notes |
|---|---|---|
| `symbol` | str | trading symbol |
| `token` | str | broker instrument token |
| `exchange` | str | `NSE`/`NFO`/`BSE`/`BFO`/`MCX`/… |
| `name` | str | underlying / company name |
| `instrument_type` | str | canonical `EQ`/`FUT`/`CE`/`PE` (or raw) |
| `expiry` | str | ISO `YYYY-MM-DD`; `""` for non-derivatives |
| `strike` | float | **rupees**; `-1.0` for non-options |
| `lot_size` | int | contract lot size |
| `tick_size` | float | minimum price move in **rupees** |

Each broker absorbs its own quirks here (Angel: paise→rupees, `28NOV2024`→ISO,
OPTIDX/OPTSTK→CE/PE; Kite is already close to canonical).
