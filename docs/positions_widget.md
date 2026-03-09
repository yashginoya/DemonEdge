# Positions & P&L Widget

`widget_id = "positions"` — Category: **Orders**

## Overview

Displays open positions with live P&L updates via `MarketFeed`, and today's
order book in a separate tab.  Refreshes from the broker REST API every 30
seconds, and immediately after any order is placed by `OrderEntryWidget`.

---

## File Structure

```
widgets/positions/
├── __init__.py
├── positions_widget.py    ← BaseWidget, data loading, feed, auto-refresh
├── positions_model.py     ← QAbstractTableModel for open positions
├── trades_model.py        ← QAbstractTableModel for order book
└── pnl_summary.py         ← Summary bar (Realized / Unrealized / Total / Count)
```

---

## Live P&L Calculation

Formulas applied in `PositionsModel.update_ltp()`:

```
unrealized_pnl = (ltp - average_price) × quantity
realized_pnl   = from broker position response (.pnl field)
total_pnl      = unrealized_pnl + realized_pnl
```

Angel's `.pnl` field in the position response represents **realized** P&L for
the session (trades already closed).  `unrealized_pnl` is computed client-side
from `ltp` ticks.

`AngelBroker.get_positions()` pre-computes `unrealized_pnl` on load using the
broker-provided `ltp` snapshot.  After that, live ticks from `MarketFeed` keep
`unrealized_pnl` updated without additional REST calls.

---

## Feed Subscription Lifecycle

```
on_show()
  → refresh()  →  _PositionsWorker.run()
     → broker.get_positions()  → _on_positions_ready()
        → _unsubscribe_all_feeds()
        → PositionsModel.set_positions()
        → subscribe_feed(exchange, token, _tick_callback, LTP)  ← for each open position
     → broker.get_order_book()  → _on_orders_ready()
        → TradesModel.set_orders()
  → _refresh_timer.start(30s)

_tick_callback(tick)  [feed thread]
  → _tick_signal.emit(tick)

_on_tick_ui(tick)  [main thread]
  → PositionsModel.update_ltp(token, ltp)  → dataChanged (targeted, LTP→Total columns)
  → _refresh_summary()  → PnLSummary.update()

on_hide()
  → _refresh_timer.stop()
  → BaseWidget._unsubscribe_all_feeds()  ← auto-cleanup
```

---

## Periodic REST Refresh Strategy (30-second timer)

On each timer tick:
1. `_PositionsWorker` calls `broker.get_positions()` and `broker.get_order_book()`.
2. `_on_positions_ready()`:
   - Calls `_unsubscribe_all_feeds()` to clear stale subscriptions.
   - Calls `PositionsModel.set_positions()` — **full reset** (quantities / averages may change from external orders).
   - Re-subscribes LTP for all positions with non-zero quantity.
   - Positions that closed (quantity = 0) are naturally dropped since subscriptions are rebuilt from scratch.

**Rationale for full reset vs merge:** A merge strategy would need to detect new/closed/modified positions and update selectively. Given 30-second intervals and the small number of positions typical for retail traders, a full reset is simpler and has no visible UI cost (`beginResetModel/endResetModel` with <50 rows is imperceptible).

---

## `PositionsModel` — targeted `dataChanged`

`update_ltp(token, ltp)` emits `dataChanged` for **the single affected row only**,
columns `COL_LTP` through `COL_TOTAL`.  This avoids triggering a full repaint of
the table on every tick.

```python
tl = self.index(i, COL_LTP)
br = self.index(i, COL_TOTAL)
self.dataChanged.emit(tl, br, [DisplayRole, ForegroundRole])
```

---

## Order Placed → Positions Refresh

`OrderEntryWidget.order_placed(order_id)` signal is connected in
`MainWindow.spawn_widget()` and `MainWindow._restore_layout()` to
`MainWindow._on_order_placed()`, which calls `PositionsWidget.refresh()`
immediately.  This ensures positions reflect the new order without waiting for
the 30-second timer.

---

## State Persistence

`save_state()` returns `{}` — positions are always loaded live from the broker.
`restore_state()` is a no-op.  Data is fetched fresh in `on_show()`.

---

## Known Issues / TODOs

- `TradesModel` shows all orders (all statuses), not just COMPLETE ones.
  Filtering to only executed trades can be added: `[o for o in orders if o.status.lower() == "complete"]`.
- Angel's position response does not always include `symboltoken` — if empty,
  LTP subscription is skipped for that position (no live updates).
- P&L for overnight/delivery positions uses the session `ltp` as reference, not
  yesterday's close.  True overnight P&L requires `close_price` from the response.
