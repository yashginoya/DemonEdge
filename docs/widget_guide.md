# Widget Guide

## Adding a New Widget

1. Create a folder under `widgets/` named after the feature, e.g. `widgets/option_chain/`.
2. Create the main widget file, e.g. `option_chain_widget.py`.
3. Subclass `BaseWidget`.
4. Set a unique `widget_id` class attribute.
5. Self-register at the bottom of the file (outside the class).
6. Import the module in `app/main_window.py` (with `# noqa: F401`) to trigger registration.
7. Add a row to the **Available Widgets** table below.

## Minimal Complete Example

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from widgets.base_widget import BaseWidget


class OptionChainWidget(BaseWidget):
    widget_id = "option_chain"   # unique — used as key in registry + layout.json

    def __init__(self, parent=None):
        super().__init__("Option Chain", parent)

        # Build UI
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("Option chain here"))
        self.setWidget(content)   # QDockWidget requires setWidget()

    # --- BaseWidget contract ---

    def on_show(self) -> None:
        # Widget became visible — subscribe to feeds
        # MarketFeed.instance().subscribe("NSE", self._token, self._on_tick)
        pass

    def on_hide(self) -> None:
        # Widget hidden or closed — unsubscribe from feeds
        # MarketFeed.instance().unsubscribe("NSE", self._token, self._on_tick)
        pass

    def save_state(self) -> dict:
        return {"symbol": self._current_symbol}

    def restore_state(self, state: dict) -> None:
        self._current_symbol = state.get("symbol", "")


# --- Self-registration (module-level, outside class) ---
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=OptionChainWidget.widget_id,
        display_name="Option Chain",
        category="Market Data",   # used to group in View → Add Widget menu
        factory=OptionChainWidget,
    )
)
```

Then in `app/main_window.py`, add:

```python
import widgets.option_chain.option_chain_widget  # noqa: F401
```

## BaseWidget Contract

| Method | When called | Required behaviour |
|---|---|---|
| `on_show()` | Widget becomes visible | Subscribe to `MarketFeed` feeds |
| `on_hide()` | Widget hidden or closed | Unsubscribe all feeds |
| `save_state() -> dict` | App exit / manual save | Return JSON-serialisable dict |
| `restore_state(state)` | App start (layout restore) | Restore from the dict |

### `instance_id`

Set by `MainWindow.spawn_widget()` after creation. Format: `"{widget_id}_{n}"` e.g. `"watchlist_0"`. Allows two instances of the same widget type to coexist and be saved/restored independently. Do not set this yourself.

### `closed` Signal

`BaseWidget` emits `closed` from its `closeEvent`. `MainWindow` connects this to deregister the widget from `_active_widgets`. You don't need to handle this in your widget.

### Feed subscriptions — recommended pattern

Use `subscribe_feed()` instead of calling `MarketFeed.instance().subscribe()` directly.
Subscriptions registered this way are **automatically cancelled** when the widget is
hidden or closed — no cleanup needed in `on_hide()`.

```python
from PySide6.QtCore import Signal

class MyWidget(BaseWidget):
    _tick_signal = Signal(object)  # private signal for thread crossing

    def __init__(self, parent=None):
        super().__init__("My Widget", parent)
        self._tick_signal.connect(self._update_ui)

    def on_show(self):
        self.subscribe_feed("NSE", self._token, self._on_feed_tick)
        # Can also pass mode: self.subscribe_feed("NSE", token, cb, SubscriptionMode.QUOTE)

    def on_hide(self):
        pass  # nothing needed — subscribe_feed() auto-cleans up

    def _on_feed_tick(self, tick):
        self._tick_signal.emit(tick)   # crosses to Qt main thread

    def _update_ui(self, tick):
        self._price_label.setText(f"{tick.ltp:.2f}")  # safe — main thread
```

Feed callbacks arrive on the feed thread. Never touch Qt widgets from there.

### Broker calls from widgets

```python
from broker.broker_manager import BrokerManager
from broker.base_broker import BrokerAPIError
from PySide6.QtCore import QRunnable, QThreadPool

class _FetchWorker(QRunnable):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def run(self):
        try:
            data = BrokerManager.get_broker().get_positions()
            self._cb(data)
        except BrokerAPIError as e:
            ...   # handle in callback

# In widget:
worker = _FetchWorker(lambda data: self._positions_signal.emit(data))
QThreadPool.globalInstance().start(worker)
```

## Widget Lifecycle

```
App start
  → MainWindow imports widget module (triggers self-registration)
  → LoginWindow: user connects
  → on_login_success()
      → LayoutManager.restore() or _load_default_layout()
          → WidgetRegistry.create(widget_id)
          → widget.restore_state(state)
          → addDockWidget(area, widget)
          → showEvent → on_show()

User hides widget
  → hideEvent → on_hide()

User shows widget again
  → showEvent → on_show()

User closes widget (X)
  → closeEvent → on_hide() → closed.emit() → MainWindow.remove_widget()

App exit
  → MainWindow.closeEvent()
      → LayoutManager.save()  calls widget.save_state() on all active widgets
```

## WidgetRegistry

```python
from app.widget_registry import WidgetRegistry

# Get all registered definitions
defs = WidgetRegistry.get_all()

# Get grouped by category (for menus)
by_cat = WidgetRegistry.get_by_category()
# → {"Market Data": [...], "Orders": [...]}

# Create a new instance
widget = WidgetRegistry.create("watchlist")
```

## Reference Implementation: WatchlistWidget

`WatchlistWidget` is the canonical example of a complete live-data widget. Study
`widgets/watchlist/` to understand the full pattern.

### File structure for a multi-file widget

```
widgets/watchlist/
├── watchlist_row.py      ← dataclass for one row's state
├── watchlist_model.py    ← QAbstractTableModel (pure data, no UI)
├── watchlist_tab.py      ← QWidget: one independent list (toolbar + table)
├── watchlist_widget.py   ← BaseWidget: tab container + self-registration
├── search_dialog.py      ← QDialog: debounced broker search
└── add_manual_dialog.py  ← QDialog: manual token entry + lookup
```

### Live data pattern (model/view separation)

```
Feed thread → _tick_callback(tick) → tick_arrived.emit(tick)
                                              ↓ (Qt queued connection)
                                     _on_tick_ui(tick)  [main thread]
                                              ↓
                                     model.update_tick(tick.token, tick)
                                              ↓
                                     dataChanged.emit(top_left, bottom_right, [roles])
                                              ↓
                                     QTableView repaints only changed rows
```

Key points:
- The model emits **targeted** `dataChanged` for only the changed row — never full `layoutChanged`.
- The tab has **one** `tick_arrived` signal regardless of how many instruments are subscribed.
  All instruments share the same `_tick_callback`; `update_tick()` routes by `tick.token`.
- Flash animation uses a 100ms `QTimer` that decrements `flash_counter` and emits `dataChanged`
  for BackgroundRole only — keeping repaint cost proportional to active tick rate.

### Subscription lifecycle for sub-widgets (QWidget, not BaseWidget)

When a widget contains sub-widgets (`WatchlistTab` inside `WatchlistWidget`),
the sub-widgets manage their own subscriptions directly:

```python
# WatchlistWidget.on_show() delegates to each tab
def on_show(self) -> None:
    for i in range(self._tabs.count()):
        tab = self._tabs.widget(i)
        tab.subscribe_all()   # tab calls MarketFeed.instance().subscribe(...)

# WatchlistWidget.on_hide() delegates to each tab
def on_hide(self) -> None:
    for i in range(self._tabs.count()):
        tab = self._tabs.widget(i)
        tab.unsubscribe_all()
```

The sub-widget (`WatchlistTab`) tracks its own `_subscribed: set[str]` to avoid
double-subscribing. `subscribe_all()` is idempotent.

## Available Widgets

| Widget ID | Display Name | Category | Module | Status |
|---|---|---|---|---|
| `watchlist` | Watchlist | Market Data | `widgets/watchlist/watchlist_widget.py` | Live (Phase 5) |
| `chart` | Chart | Market Data | `widgets/chart/chart_widget.py` | Live (Phase 6) |
| `order_entry` | Order Entry | Orders | `widgets/order_entry/order_entry_widget.py` | Placeholder (Phase 5) |
| `positions` | Positions & P&L | Orders | `widgets/positions/positions_widget.py` | Placeholder (Phase 5) |
| `feed_status` | Feed Status | System | `widgets/feed_status/feed_status_widget.py` | Live (Phase 4) |
