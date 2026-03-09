# Order Entry Widget

`widget_id = "order_entry"` — Category: **Orders**

## Overview

Full-featured order entry form supporting all Angel SmartAPI order types.
Implemented as a `BaseWidget` (`QDockWidget`) that embeds an `OrderForm` widget.
Order placement runs on a `QThread` worker so the UI never blocks.

---

## File Structure

```
widgets/order_entry/
├── __init__.py
├── order_entry_widget.py          ← BaseWidget, placement flow, status bar
├── order_form.py                  ← Embedded form (fields, validation, LTP)
└── order_confirmation_dialog.py   ← Pre-trade confirmation popup
```

---

## Order Type Visibility Rules

| Order Type selected | Price field | Trigger field |
|---|---|---|
| MARKET      | Disabled (cleared) | Hidden |
| LIMIT       | Enabled            | Hidden |
| SL          | Enabled            | Shown  |
| SL-M        | Disabled (cleared) | Shown  |

| Variety selected | Bracket block | Trigger field |
|---|---|---|
| NORMAL  | Hidden | per Order Type rules above |
| BRACKET | Shown  | Hidden (SL handled by bracket stoploss) |
| COVER   | Hidden | Always shown |

---

## Validation Logic

All checks run on the main thread before the confirmation dialog is shown.
On failure, an inline red error label appears below the form — no `QMessageBox`.

| Check | Condition |
|---|---|
| Instrument selected | `_instrument is not None` |
| Quantity | `qty > 0` |
| Price | `> 0` if LIMIT or SL order type |
| Trigger | `> 0` if SL or SL-M or COVER variety |
| Bracket squareoff | `> 0` if BRACKET variety |
| Bracket stoploss | `> 0` if BRACKET variety |

---

## Angel API Parameter Mapping

`OrderForm.get_order_params()` returns a dict matching `SmartConnect.placeOrder()`:

| Form field | API key | Notes |
|---|---|---|
| Variety (NORMAL/BRACKET/COVER) | `variety` | BRACKET → `ROBO`, COVER → `COVER`, NORMAL → `NORMAL` |
| Symbol | `tradingsymbol` | from `Instrument.symbol` |
| Token | `symboltoken` | from `Instrument.token` |
| BUY/SELL | `transactiontype` | |
| Exchange | `exchange` | from `Instrument.exchange` |
| MARKET/LIMIT/SL/SL-M | `ordertype` | SL → `STOPLOSS`, SL-M → `STOPLOSS_MARKET` |
| INTRADAY/DELIVERY | `producttype` | |
| Duration | `duration` | always `"DAY"` |
| Price | `price` | `"0"` for MARKET/SL-M |
| Trigger | `triggerprice` | `"0"` if not applicable |
| Quantity | `quantity` | |
| Squareoff | `squareoff` | bracket only |
| Stoploss | `stoploss` | bracket only |
| Trailing SL | `trailingStopLoss` | bracket only |

---

## Watchlist → Order Entry Integration

`WatchlistTab` emits `instrument_selected(Instrument)` on row double-click.
`WatchlistWidget` relays this as `instrument_for_order_entry(Instrument)`.
`MainWindow.spawn_widget()` connects `instrument_for_order_entry` to
`send_instrument_to_order_entry()`, which calls `OrderEntryWidget.set_instrument()`.

```
WatchlistTab.doubleClicked
  → WatchlistTab.instrument_selected
  → WatchlistWidget.instrument_for_order_entry
  → MainWindow.send_instrument_to_order_entry()
  → OrderEntryWidget.set_instrument()
  → OrderForm.set_instrument()  +  subscribe_feed(LTP)
```

Same wiring is applied in `_restore_layout()` so it works after layout restore.

---

## LTP Feed Subscription

- `OrderForm.ltp_feed_callback(tick: Tick)` is registered via `subscribe_feed()`.
- Called on the feed thread; emits `_ltp_signal` to cross to the main thread.
- `_on_ltp_main` updates the LTP label safely.
- On instrument change: previous subscription unsubscribed via
  `_unsubscribe_all_feeds()`, new subscription registered immediately.
- On widget hide/close: `BaseWidget._unsubscribe_all_feeds()` runs automatically.

---

## State Persistence

`save_state()` persists: `side`, `order_type`, `product_type`, `variety`, and the
selected `instrument` (symbol, token, exchange, name, instrument_type).

`restore_state()` rehydrates all form fields and re-subscribes the LTP feed for
the restored instrument.

---

## Known Issues / TODOs

- `BaseBroker.place_order(params: dict)` now accepts the raw Angel API dict directly.
  A future multi-broker abstraction may need a broker-agnostic order model.
- AMO (After Market Order) variety not exposed in the UI — requires `"AMO"` variety.
- Bracket + Cover orders for NFO options may have exchange-specific constraints not
  validated client-side.
