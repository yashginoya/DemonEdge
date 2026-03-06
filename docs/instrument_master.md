# Instrument Master Reference

## Overview

`InstrumentMaster` (`broker/instrument_master.py`) provides fast, offline symbol
search by downloading the broker's full instrument list once per day and caching
it locally.  All `SearchDialog` lookups are in-memory — no network round-trip
per keystroke.

## Cache Location

```
data/instrument_master/{broker_key}_{YYYY-MM-DD}.json
```

- **Angel:** `data/instrument_master/angel_2026-03-06.json`
- The directory is in `.gitignore` — never committed.
- Files from previous days are kept as fallback but not auto-deleted.

## Source URL (Angel)

```
https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json
```

Public CDN — no authentication required.  ~50,000 records, ~8 MB.

## Lifecycle

```
on_login_success()
  → _load_instrument_master()
      → _InstrumentMasterWorker(QThread).start()
          → InstrumentMaster.ensure_loaded(broker)
              → check data/instrument_master/angel_YYYY-MM-DD.json
              → if missing: download from CDN
              → _build_index()  ← builds (symbol_lower, name_lower, record) list
              → emit finished(count)
  → _on_im_loaded(count): status bar shows "Instruments: 54,321"
```

## `ensure_loaded(broker)` Logic

1. If already loaded (`_loaded = True`) → return immediately.
2. Check for `{broker_key}_{today}.json` in cache dir.  If found → load it.
3. If not found → download from `broker.instrument_master_url` → save → load.
4. If download fails → try most recent `{broker_key}_*.json` in cache dir.
5. If no cache at all → raise `RuntimeError`.

## Search Index

Built once in `_build_index()`:
- `_index`: list of `(symbol_lower, name_lower, record_dict)` — iterated for search.
- `_token_map`: `{"NSE:2885": record, ...}` — O(1) lookup by exchange + token.

## `search(query, exchange="", max_results=100)`

Scoring (higher = better match):

| Score | Condition |
|---|---|
| 3 | `symbol.lower().startswith(query)` |
| 2 | `name.lower().startswith(query)` |
| 1 | query appears anywhere in symbol or name |

Results sorted by score descending, then symbol ascending.

Runs synchronously on the Qt main thread.  Typical time: **<10 ms** for 50k records.

## `get_by_token(exchange, token) → Instrument | None`

O(1) lookup via `_token_map`.  Used internally by `AngelBroker.search_instruments()`.

## `InstrumentMaster` Singleton

Follows the module-level singleton pattern:

```python
from broker.instrument_master import InstrumentMaster  # module-level instance

# Load (in worker thread after login):
count = InstrumentMaster.ensure_loaded(broker)

# Search (main thread):
results = InstrumentMaster.search("reliance", exchange="NSE")

# Token lookup:
inst = InstrumentMaster.get_by_token("NSE", "2885")

# Check before searching:
if InstrumentMaster.is_loaded():
    ...
```

## Angel JSON Record Format

```json
{
  "token": "2885",
  "symbol": "RELIANCE-EQ",
  "name": "RELIANCE INDUSTRIES LTD",
  "expiry": "",
  "strike": "-1",
  "lotsize": "1",
  "instrumenttype": "EQ",
  "exch_seg": "NSE",
  "tick_size": "5"
}
```

- `tick_size` is in **paise** — `InstrumentMaster` converts to rupees (`/ 100`).
- `strike` is `"-1"` for non-options.
- `exch_seg` maps to the `Instrument.exchange` field (`"NSE"`, `"BSE"`, `"NFO"`, `"MCX"`).

## Adding a New Broker

1. Implement `broker_key` and `instrument_master_url` properties in the new broker class.
2. The JSON at that URL must be an array of objects with at minimum: `token`, `symbol`,
   `name`, `exch_seg`.  Override `_to_instrument()` if the field names differ.
