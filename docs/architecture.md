# Architecture Overview

## Layer Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                          UI Layer                                │
│  app/main_window.py  — dock shell, toolbar, menu, status bar     │
│  app/login_window.py — QDialog: auth form / returning user       │
│  app/theme.py        — global QSS dark theme                     │
│  widgets/            — QDockWidget subclasses via BaseWidget      │
└──────────────────────────────┬───────────────────────────────────┘
                               │ uses
          ┌────────────────────┼────────────────────┐
          │                    │                    │
┌─────────▼────────┐  ┌────────▼────────┐  ┌───────▼──────────────┐
│  Widget Registry │  │ Layout Manager  │  │    Broker Layer       │
│  app/widget_     │  │ app/layout_     │  │  broker/base_broker   │
│  registry.py     │  │ manager.py      │  │  broker/angel_broker  │
│  Catalog +       │  │ save/restore    │  │  broker/broker_       │
│  factory         │  │ layout.json     │  │  manager.py           │
└─────────┬────────┘  └─────────────────┘  └───────┬──────────────┘
          │                                         │
          │                              ┌──────────▼──────────────┐
          │                              │     Feed Layer           │
          │                              │  feed/market_feed.py    │
          │                              │  MarketFeed singleton    │
          │                              │  pub/sub, one WebSocket  │
          │                              └──────────┬──────────────┘
          │                                         │
          └──────────────────┬──────────────────────┘
                             │ models
              ┌──────────────▼───────────────┐
              │       Shared Models           │
              │  models/  (dataclasses)       │
              │  Instrument, Tick,            │
              │  Order, Position              │
              └───────────────────────────────┘

              ┌───────────────────────────────┐
              │      Utils / Config           │
              │  utils/logger.py              │
              │  utils/config.py              │
              └───────────────────────────────┘
```

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `main.py` | Entry point: init singletons, apply theme, create QApplication, show MainWindow + login |
| `app/main_window.py` | Dock shell: toolbar, menu bar, status bar, banner, widget spawn/remove, auto-save |
| `app/login_window.py` | Modal QDialog: Mode A (form) / Mode B (returning user). Worker thread connect. |
| `app/widget_registry.py` | Catalog of all widget types + factory; populated by widget module self-registration |
| `app/layout_manager.py` | Save/restore dock layout to/from `config/layout.json`; atomic write |
| `app/theme.py` | Global dark QSS applied to QApplication before any windows are created |
| `app/app_state.py` | Global mutable state: selected instrument, connection status |
| `broker/base_broker.py` | Abstract interface for all broker operations |
| `broker/broker_manager.py` | Singleton holding the active BaseBroker instance |
| `broker/angel_broker.py` | Angel SmartAPI implementation of BaseBroker |
| `feed/market_feed.py` | Single WebSocket feed, pub/sub dispatch to widget callbacks |
| `feed/feed_models.py` | SubscriptionMode enum for tick data granularity |
| `widgets/base_widget.py` | Base class: lifecycle hooks, state persistence contract |
| `widgets/*/` | Individual feature widgets (self-contained) |
| `models/` | Shared typed dataclasses (no logic) |
| `utils/logger.py` | Centralized rotating file + console logger |
| `utils/config.py` | Singleton YAML config reader with dot-notation access |

## Data Flow

### Live tick data
```
Angel WebSocket
    → MarketFeed._on_tick(tick)
    → iterates _subscribers[exchange:token]
    → calls callback(tick)  [on feed thread]
    → widget re-emits via Qt signal  [crosses to Qt main thread]
    → widget UI updates
```

### Broker REST call
```
Widget action (Qt main thread)
    → QThreadPool worker
    → BrokerManager.get_broker().some_method()
    → AngelBroker wraps SmartAPI call
    → result emitted back via Qt signal
    → widget UI updates on main thread
```

## Singleton Pattern

All singletons (`BrokerManager`, `MarketFeed`, `AppState`, `Config`) use a module-level instance pattern:
```python
class _Foo:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

Foo = _Foo()
```

Import `Foo` directly — do not instantiate.

## Thread Safety Rules

- All Qt widget updates must happen on the **main thread**.
- Feed callbacks are invoked on the feed thread. Always use `emit()` on a Qt signal to cross threads.
- `MarketFeed._subscribers` is protected by `threading.Lock`.
- Broker REST calls run in `QThreadPool` workers — never block the main thread.

## Inter-Widget Communication

Widgets are self-contained and do not hold references to each other.
Cross-widget communication goes through `MainWindow` as the message broker,
using Qt signals.

### Pattern: Watchlist → Order Entry

```
WatchlistTab.doubleClicked
  → WatchlistTab.instrument_selected (Signal)
  → WatchlistWidget.instrument_for_order_entry (relay Signal)
  → MainWindow.send_instrument_to_order_entry()
  → OrderEntryWidget.set_instrument(instrument)
```

`MainWindow.spawn_widget()` connects `instrument_for_order_entry` immediately
after creating any `WatchlistWidget`.  `_restore_layout()` does the same for
restored widgets so the connection is never missed.

### Pattern: Order Placed → Positions Refresh

```
OrderEntryWidget._on_order_success()
  → OrderEntryWidget.order_placed (Signal, carries order_id)
  → MainWindow._on_order_placed()
  → PositionsWidget.refresh()
```

Connected in `spawn_widget()` and `_restore_layout()` for the same reason.

### Rules

- Widgets **never** hold direct references to sibling widgets.
- All cross-widget routing goes through `MainWindow` methods.
- `MainWindow` uses `get_first_widget_of_type(widget_id)` to find target widgets.
- If the target widget is not open, the signal is silently dropped (no error).

---

## pyqtgraph Configuration

pyqtgraph global options **must be set before `QApplication` is created** in `main.py`:

```python
import pyqtgraph as pg
pg.setConfigOption('background', '#0d1117')
pg.setConfigOption('foreground', '#8b949e')
pg.setConfigOption('antialias', True)
```

Setting these after `QApplication` initialisation may have no effect on already-created
widgets. This is why the config is at module level in `main.py`, before `QApplication()`.
