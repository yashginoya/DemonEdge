# Changelog

---

## 2026-03-06 — Add README.md

### Added
- `README.md` — project README covering description, features, tech stack, prerequisites, installation, configuration, running, architecture overview, project structure, and contribution notes. Reflects only what is currently implemented.

---

## 2026-03-06 — Fix: remove blank central widget gap between dock widgets

### Fixed
- `app/main_window.py` — Blank space no longer appears between docked widgets (e.g. Watchlist and Chart). Root cause: `_setup_central_widget` created an expanding `_placeholder` QWidget inside the central area that Qt always reserved regardless of dock coverage.

### Changed
- `app/main_window.py` — `_setup_central_widget()` replaced with a zero-size dummy central widget (`setMaximumSize(0, 0)`, `setSizePolicy(Fixed, Fixed)`, `.hide()`). Dock widgets now expand to fill the entire window area edge-to-edge.
- `app/main_window.py` — Added `_setup_banner()`. The disconnected warning banner (previously a `QFrame` inside the central widget) is now a secondary `QToolBar` (`ConnectionBanner`) added to `TopToolBarArea` with `addToolBarBreak`. It is shown/hidden via the same `self._banner.setVisible()` calls — no callers changed.
- `app/main_window.py` — `_load_default_layout()` updated: watchlist left (280px), chart fills center, order_entry splits right (300px), positions+feed_status tabbed at bottom (180px). Explicit `splitDockWidget` calls ensure edge-to-edge fill.
- `app/main_window.py` — Removed unused imports: `QFrame`, `QHBoxLayout`, `QVBoxLayout`. Added `QSizePolicy`.

### Architecture Decisions
- Banner moved to a toolbar instead of a central widget child: toolbars collapse to zero height when hidden (`.setVisible(False)`), whereas `QMainWindow` always reserves space for the central widget even when its contents are invisible.

---

## 2026-03-06 — Instrument Master: local symbol cache for instant search

### Added
- `broker/instrument_master.py` — `_InstrumentMaster` singleton (accessed as `InstrumentMaster`). Downloads Angel's public CDN JSON (`OpenAPIScripMaster.json`) once per day and caches it as `data/instrument_master/angel_YYYY-MM-DD.json`. Builds a `(symbol_lower, name_lower, record)` index and a `{exchange:token → record}` token map. `search(query, exchange, max_results)` scores prefix matches (score 3 symbol, 2 name, 1 anywhere) and returns sorted `Instrument` list. `get_by_token(exchange, token)` is O(1). Falls back to most recent cached file if download fails. ~50k records, search completes in <10 ms on main thread.
- `docs/instrument_master.md` — full reference: cache location, lifecycle, search scoring, JSON record format, adding a new broker.
- `data/instrument_master/` directory (in `.gitignore`).

### Changed
- `models/instrument.py` — added optional fields `expiry: str = ""`, `strike: float = -1.0`, `lot_size: int = 1`, `tick_size: float = 0.05`. Backward-compatible (all default). Populated when instruments come from the master.
- `broker/base_broker.py` — added two abstract properties: `broker_key: str` and `instrument_master_url: str`. Required by `InstrumentMaster.ensure_loaded()`.
- `broker/angel_broker.py` — implemented `broker_key` → `"angel"` and `instrument_master_url` → Angel CDN URL. `search_instruments()` now delegates to `InstrumentMaster.search()` when loaded; falls back to live `searchScrip` API if master not yet available.
- `app/main_window.py` — added `_InstrumentMasterWorker(QThread)` that calls `InstrumentMaster.ensure_loaded(broker)` off the main thread. Called in `on_login_success()` immediately after feed start. Added `_sb_instruments` permanent label to status bar showing "Instruments: N" (or "loading…" / "—" on error).
- `widgets/watchlist/search_dialog.py` — removed `_SearchWorker` (QThread) entirely. `_run_search()` now calls `InstrumentMaster.search()` synchronously. Min query length reduced from 3 → 2. Dialog width enlarged to 500px. Result rows show expiry for F&O instruments. Exchange filter now re-filters already-fetched results instantly without re-searching.
- `.gitignore` — added `data/instrument_master/` entry.
- `docs/broker_api.md` — documented `broker_key` and `instrument_master_url` properties; updated `search_instruments` row.

### Architecture Decisions
- `InstrumentMaster` is a module-level singleton (`InstrumentMaster = _InstrumentMaster()`) matching the `BrokerManager` / `MarketFeed` / `AppState` pattern.
- Search runs synchronously on the main thread. 50k-record linear scan takes <10 ms in Python — acceptable given 400ms debounce. No worker thread needed for the search itself.
- Cache files are named `{broker_key}_{YYYY-MM-DD}.json` — multiple brokers can coexist without collision. Old files are kept as fallback but not auto-cleaned.
- `AngelBroker.search_instruments()` retains the live API fallback so the app remains functional if the instrument master fails to load on first login.

### Known Issues / TODOs
- Old cache files (`angel_YYYY-MM-DD.json` from previous days) accumulate in `data/instrument_master/`. Could add auto-cleanup of files older than N days.
- `tick_size` division by 100 (paise→rupees) is Angel-specific. If a future broker stores tick_size differently, `_to_instrument()` in `InstrumentMaster` needs a broker-aware override.

---

## 2026-03-06 — Phase 6: OHLC Chart Widget (pyqtgraph)

### Added
- `widgets/chart/timeframe.py` — `Timeframe` enum (M1/M3/M5/M15/H1/D1) with `TimeframeInfo` dataclass holding `label`, `angel_interval`, and `seconds`.
- `widgets/chart/ohlc_item.py` — `OHLCItem(pg.GraphicsObject)`: custom OHLC bar renderer. Draws via direct `paint()` using `QPainter` primitives (not `QPicture`). Stores data as numpy structured array. `set_data()` / `update_last_bar()` / `append_bar()`. `boundingRect()` always returns a cached `QRectF`. Clips off-screen bars via `option.exposedRect`. Green pen (`#3fb950`) for up bars, red (`#f85149`) for down.
- `widgets/chart/volume_item.py` — `VolumeItem(pg.GraphicsObject)`: volume bar renderer matching `OHLCItem` pattern. Filled rectangles with dark green/red. `set_bar_width()` syncs width from OHLC item. Same `boundingRect` caching pattern.
- `widgets/chart/chart_data_manager.py` — `ChartDataManager`: all data logic. `_HistoricalWorker(QThread)` fetches 500 bars via `broker.get_historical_data()`. `_parse_timestamp()` handles Angel IST string formats. `_get_bar_start(dt, tf)` floors datetime to nearest bar boundary using `math.floor(ts / secs) * secs`. `on_tick(tick)` compares bar start to current bar — emits `bar_updated` or `bar_appended`. `ChartDataSignals(QObject)` is the signal bridge.
- `widgets/chart/chart_view.py` — `ChartView(QWidget)`: pyqtgraph layout with `GraphicsLayoutWidget`. Price pane (70%) + volume pane (30%, max 120px). `_TimeAxisItem(pg.AxisItem)` formats unix timestamps as `HH:MM` / `dd Mon`. X-axes linked so pan/zoom syncs. Crosshair (`InfiniteLine` H+V). OHLCV `LabelItem` anchored top-left updates on `sigMouseMoved`. `_auto_scroll` flag: scrolls right on `append_bar` unless user has panned left; resets when view returns to right edge.
- `widgets/chart/chart_widget.py` — Full rewrite of placeholder. `ChartWidget(BaseWidget)`: toolbar with symbol button (opens `SearchDialog`), timeframe toggle buttons, status label. Subscribes in `QUOTE` mode for volume. `_load_chart()` unsubscribes previous feed, starts historical load, re-subscribes. `_tick_callback` (feed thread) → `_tick_signal.emit` → `_on_tick_main` (main thread) → `data_manager.on_tick()`. `save_state`/`restore_state` persist instrument + timeframe.
- `docs/chart_widget.md` — New doc: rendering architecture (direct paint vs QPicture), bar aggregation flow, auto-scroll, watchlist integration, timeframe table, known limitations.
- `pyqtgraph==0.14.0` + `numpy==2.4.2` added to `pyproject.toml` via `uv add`.

### Changed
- `main.py` — Added `import pyqtgraph as pg` and `pg.setConfigOption(...)` calls at module level before `QApplication` (required by pyqtgraph: config must precede any widget creation).
- `app/main_window.py` — Added `get_first_widget_of_type(widget_id) -> BaseWidget | None`: iterates `_active_widgets`, returns first widget with matching `widget_id`. Used by watchlist "Add to Chart".
- `widgets/watchlist/watchlist_tab.py` — Enabled "Add to Chart" context menu item (was disabled placeholder in Phase 5). `_add_to_chart(instrument)` gets `QApplication.activeWindow()`, calls `get_first_widget_of_type("chart")`, then `chart._load_chart(instrument, chart._timeframe)`.
- `docs/architecture.md` — Added pyqtgraph config note (must set before QApplication).
- `docs/widget_guide.md` — Updated Chart status from Placeholder to Live.

### Architecture Decisions
- **Direct `paint()` not `QPicture`**: `QPicture` pre-renders bars and only regenerates on explicit `generatePicture()` call. Qt does NOT call `generatePicture()` on `update()` — only on zoom/pan. So live tick updates would not repaint. Direct `paint()` is called by Qt on every `update()`, giving immediate live repaints.
- **Cached `boundingRect()`**: pyqtgraph calls `boundingRect()` on every layout pass, mouse event, and zoom. Computing min/max over the full numpy array each time is O(n) and causes visible lag. Cache is recomputed only when data structurally changes (set_data, append_bar) or when h/l of the last bar changes (update_last_bar).
- **numpy structured arrays for bar storage**: provides O(1) column access (`data['h']`) and efficient min/max via numpy vectorized ops. Avoids Python list-of-dict overhead in the paint loop.
- **`math.floor(ts / secs) * secs` for bar boundaries**: works correctly across DST boundaries and timezone offsets because unix timestamps are always UTC-based seconds — no timezone math needed for flooring.
- **`_get_bar_start` returns float not datetime**: directly comparable to `_current_bar_time` (also float) without datetime construction overhead on every tick.
- **QUOTE mode subscription for chart**: provides volume data (`tick.volume`) needed for volume pane. LTP mode would give prices only.
- **`QApplication.activeWindow()` for watchlist → chart routing**: avoids passing `MainWindow` reference through the widget hierarchy. `activeWindow()` returns the topmost window of the application which is `MainWindow`. This is simpler and sufficient since we only ever have one `MainWindow`.

### Known Issues / TODOs
- Volume from QUOTE mode ticks is cumulative (Angel sends cumulative daily volume). The data manager adds `tick.volume` per tick which may overcount intraday. SNAP_QUOTE mode sends volume delta per tick — switch when needed.
- Historical data limited to 500 bars (no pagination). Angel API supports up to 60 days for minute data.
- No technical indicators (MA, VWAP, RSI) — planned for Phase 7.
- `ChartWidget.on_show()` re-subscribes only the current instrument. If `_instrument` is None (fresh widget), shows placeholder. This is intentional — can't subscribe without knowing what to chart.

---

## 2026-03-06 — Phase 5: Live Watchlist Widget

### Added
- `widgets/watchlist/watchlist_row.py` — `WatchlistRow` dataclass: `instrument`, `ltp`, `prev_close`, `change`, `change_pct`, `last_tick_direction` (+1/-1/0), `flash_counter` (counts down from 3).
- `widgets/watchlist/watchlist_model.py` — `WatchlistModel(QAbstractTableModel)`: 5 columns (Symbol, Exch, LTP, Change, Chg%). `data()` handles DisplayRole (formatted numbers, sign prefix), ForegroundRole (green/red/muted for Change/Chg%), BackgroundRole (flash colours `#1a3a2a`/`#3a1a1a` during flash, alternating dark rows otherwise), TextAlignmentRole, FontRole (bold LTP). `update_tick()` sets `flash_counter=3` and emits targeted `dataChanged`. `update_initial_ltp()` for REST-fetched initial price. `tick_flash_step()` decrements counters and returns changed row indices. `add_instrument()` (duplicate check by token), `remove_instrument()`, `get_all_instruments()`, `get_row()`.
- `widgets/watchlist/search_dialog.py` — `SearchDialog(QDialog)`: 440×380 modal. `_SearchWorker(QThread)` calls `broker.search_instruments()` off main thread. 400ms debounce via `QTimer.singleShot`. Exchange filter combo (All/NSE/BSE/NFO/MCX) applied client-side after fetch. `QListWidget` results with `UserRole` storing `Instrument`. `instrument_selected = Signal(object)`. Keyboard: Enter selects, Escape closes, Down Arrow moves focus to list.
- `widgets/watchlist/add_manual_dialog.py` — `AddManualDialog(QDialog)`: 320×240 fixed. Exchange combo + Token input + Symbol input + Lookup button. `_LookupWorker(QRunnable)` verifies token via `broker.get_ltp()`. Add button enabled after successful lookup OR when symbol field manually filled. `instrument_selected = Signal(object)`.
- `widgets/watchlist/watchlist_tab.py` — `WatchlistTab(QWidget)`: toolbar (search input, Search btn, + Manual btn, Remove btn) + `QTableView` + status label. `tick_arrived = Signal(object)` bridges feed thread → main thread. `_LtpFetchWorker(QRunnable)` fetches initial LTP via REST on instrument add. `_flash_timer` at 100ms decrements flash counters and emits targeted `dataChanged` for BackgroundRole. Row context menu: Copy Symbol, Copy Token, Remove, Add to Chart (disabled). Delete key removes selected row. `subscribe_all()` / `unsubscribe_all()` for parent widget lifecycle. `save_state()` / `restore_state()` persists instrument list.
- `widgets/watchlist/watchlist_widget.py` — Full rewrite of placeholder. `WatchlistWidget(BaseWidget)`: multi-tab `QTabWidget`. [+] corner button adds tabs via `QInputDialog`. Double-click tab renames. Right-click tab → context menu (Rename, Close Tab — last tab undeletable). `on_show()` calls `tab.subscribe_all()` for all tabs; `on_hide()` calls `tab.unsubscribe_all()`. `save_state()` / `restore_state()` persists tab names, active tab index, and each tab's instrument list.

### Architecture Decisions
- **`WatchlistTab` is a `QWidget`, not a `BaseWidget`**: tabs are sub-widgets inside the dock — they're not independently dockable. The parent `WatchlistWidget` (which is the `BaseWidget`) orchestrates `on_show`/`on_hide` by delegating to `tab.subscribe_all()` / `tab.unsubscribe_all()`.
- **Single `tick_arrived` signal per tab, all instruments share one callback**: `_tick_callback(tick)` emits `tick_arrived(tick)` regardless of which instrument triggered it. `_on_tick_ui` dispatches by `tick.token` to `model.update_tick()`. This is efficient — one signal crossing per tick instead of one per instrument per tab.
- **Flash animation via 100ms `QTimer` + `flash_counter = 3`**: gives a ~300ms visible flash with only `dataChanged` (BackgroundRole) emitted — no full model reset. Flash timer only emits for rows where `flash_counter > 0`, keeping repaint cost proportional to active tick rate.
- **`prev_close` from REST LTP on add**: `get_ltp()` sets both `ltp` and `prev_close` to the same value on add (change shows 0.00 flat until live ticks move it). This avoids the complexity of fetching historical OHLCV data just for prev close. Future improvement: subscribe in SNAP_QUOTE mode to get `close` field from the feed directly.
- **Debounce 400ms in SearchDialog**: prevents spamming `search_instruments()` on every keystroke. 400ms chosen to feel responsive while still reducing API calls significantly (user pauses naturally at this interval).
- **`_Signals` inner class as `QWidget` subclass in workers**: `QRunnable` cannot have Qt signals; the `_Signals(QWidget)` pattern gives signals to a worker without making it a `QThread`. The `_Signals` instance is created on the main thread in `__init__` before the worker runs, which is required for `QObject` creation.

### Known Issues / TODOs
- `get_ltp()` in `AngelBroker` passes `token` as `tradingsymbol` to Angel's REST API — may not return accurate LTP for all tokens. Will be superseded by SNAP_QUOTE feed data in a future improvement.
- Change / Chg% shows flat (0.00) immediately after adding an instrument (prev_close = ltp from REST). True daily P&L requires yesterday's close from historical data API.
- Multiple `WatchlistWidget` instances (two docked watchlists) work independently — each has its own tabs and `_subscribed` set. MarketFeed deduplicates at the WS level so subscribing the same token twice is safe.

---

## 2026-03-06 — Phase 4: Full MarketFeed Implementation (Angel SmartWebSocketV2)

### Added
- `feed/market_feed_signals.py` — `MarketFeedSignals(QObject)`: Qt signal bridge for the non-QObject `_MarketFeed`. Signals: `feed_connected`, `feed_disconnected`, `feed_error(str)`, `tick_received(object)`. Instance is lazy-init'd on first `.signals` access (after `QApplication` exists).
- `widgets/feed_status/feed_status_widget.py` — `FeedStatusWidget`: live dockable system widget. Shows feed status dot (green/red/amber), active subscription count, last tick timestamp, ticks-per-second counter (1-second rolling window). Self-registers as `"feed_status"` / `"System"`. Wires to `MarketFeed.signals` in `__init__` (lifecycle-independent — always monitoring).
- `widgets/feed_status/__init__.py` — package marker.

### Changed
- `models/tick.py` — Full rewrite to match `SmartWebSocketV2` parsed dict fields. New fields: `token`, `exchange_type` (int), `subscription_mode` (int), `sequence_number`, `exchange_timestamp` (datetime). LTP is `float` in **rupees** (converted from paise on parse). Optional QUOTE/SNAP_QUOTE fields (`last_traded_quantity`, `average_traded_price`, `volume`, `total_buy_quantity`, `total_sell_quantity`, `open`, `high`, `low`, `close`) default to `None` in LTP mode.
- `feed/feed_models.py` — Added `DEPTH = 4` to `SubscriptionMode`. Added `ExchangeType` IntEnum (NSE_CM=1, NSE_FO=2, BSE_CM=3, BSE_FO=4, MCX_FO=5). Added `exchange_str_to_type(exchange: str) -> ExchangeType` and `exchange_type_to_str(int) -> str` helpers (with reverse map).
- `feed/market_feed.py` — Full replacement. `connect(broker)` starts a daemon thread running `SmartWebSocketV2.connect()`. `_on_open` flushes pending subscriptions and emits `feed_connected`. `_on_data` parses dict → Tick (paise→rupees), dispatches to subscriber callbacks, emits `tick_received`. `_on_error(*args)` emits `feed_error`. `_on_close` emits `feed_disconnected`. `subscribe()` sends to WS immediately if connected, else queues in `_pending`. `_ws_subscribed` set deduplicates WS calls for same token+mode. `subscriber_count()` public helper for FeedStatusWidget.
- `broker/angel_broker.py` — Added public properties: `auth_token`, `api_key`, `client_code` (maps to `_client_id`), `feed_token`. Required by `MarketFeed.connect(broker)`.
- `widgets/base_widget.py` — Added `_feed_subscriptions: list` in `__init__`. Added `subscribe_feed(exchange, token, callback, mode=LTP)` — subscribes and tracks for auto-cleanup. Added `_unsubscribe_all_feeds()` — cancels all tracked subscriptions. `hideEvent` and `closeEvent` now call `_unsubscribe_all_feeds()` after `on_hide()`.
- `app/main_window.py` — Added `import widgets.feed_status.feed_status_widget` (self-registration). Added `_tb_feed_dot` + `_tb_feed_status` toolbar labels (between broker info and clock). `on_login_success()` now: wires `MarketFeed.signals` → toolbar slots, calls `MarketFeed.connect(broker)`. `_on_disconnect()` now calls `MarketFeed.disconnect()` before broker disconnect. `closeEvent` calls `MarketFeed.disconnect()` on exit. Added `_on_feed_connected()`, `_on_feed_disconnected()`, `_on_feed_error()`, `_set_feed_ui()` helpers. `_load_default_layout()` now spawns `feed_status` tabbed alongside `positions`.
- `docs/market_feed.md` — Full rewrite: live API, Tick model, ExchangeType, SubscriptionMode, signals, reconnection behaviour, deduplication.
- `docs/widget_guide.md` — Updated feed subscription section to use `subscribe_feed()`. Added `feed_status` to Available Widgets table.

### Architecture Decisions
- **`MarketFeedSignals` lazy init**: `MarketFeed = _MarketFeed()` is instantiated in `main.py` before `QApplication`. Creating a `QObject` before `QApplication` is undefined behaviour. Solution: `signals` is a property that creates `MarketFeedSignals()` on first access (guaranteed to be after `QApplication` in `on_login_success`).
- **`connect(broker)` takes broker object**: avoids coupling `MarketFeed` to `BrokerManager` or `AngelBroker`. Any broker exposing `auth_token`, `api_key`, `client_code`, `feed_token` properties works.
- **Daemon thread for WebSocket**: `SmartWebSocketV2.connect()` is blocking (`wsapp.run_forever()`). Running it on `threading.Thread(daemon=True)` prevents it from keeping the process alive after Qt exits.
- **`_ws_subscribed` deduplication set**: prevents double-subscribing the same token+mode to the WebSocket when multiple widgets subscribe to the same instrument. Each widget still gets its own callback in `_subscribers`.
- **Pending queue for pre-connect subscriptions**: widgets may call `subscribe_feed()` in `on_show()` before the feed is up. Queued items are flushed in `_on_open` after the WebSocket handshake.
- **`RESUBSCRIBE_FLAG` auto-reconnect**: `SmartWebSocketV2` sets this flag internally on first `subscribe()`. On reconnect the library calls its own `resubscribe()` — no app-level reconnect logic needed. `_ws_subscribed` is cleared on `disconnect()` so a manual reconnect re-subscribes correctly.
- **`_on_error(*args)` variadic**: SmartWebSocketV2 may call `on_error(type_str, msg_str)` or with different arity depending on version. Using `*args` and taking `args[-1]` as the message is defensive.
- **`FeedStatusWidget` connects in `__init__`**: unlike data widgets, FeedStatusWidget monitors feed infrastructure rather than market data. Its signal connections are lifecycle-independent (no subscribe/unsubscribe in on_show/on_hide).
- **`subscribe_feed()` auto-cleanup in `BaseWidget`**: reduces boilerplate in widget implementations. `on_hide()` remains abstract (for custom logic) but `_unsubscribe_all_feeds()` always runs after it on hide/close.

### Known Issues / TODOs
- `SmartWebSocketV2` reconnection after unexpected close: library handles resubscription via `RESUBSCRIBE_FLAG`, but `_on_open` does not re-fire on reconnects (library calls `resubscribe()` directly). Pending subscriptions queued during a disconnect window will not be flushed on reconnect — only on the first connect.
- Feed status toolbar does not show tick rate (TPS) — that detail is in the `FeedStatusWidget` dock.
- Placeholder widgets (watchlist, chart, order_entry, positions) still show static labels — real implementations in Phase 5/6.

---

_Maintained by Claude. Updated after every task. Read this at the start of every session before asking Yash anything._

---

## 2026-03-06 — Phase 3: MainWindow Dock Shell, Widget Registry & Layout Persistence

### Added
- `app/widget_registry.py` — `WidgetDefinition` dataclass + `_WidgetRegistry` singleton. `register()`, `get_all()`, `get_by_category()` (sorted), `create(widget_id)`. Widget modules self-register at import time.
- `app/layout_manager.py` — `_LayoutManager` singleton. `save()` (atomic write via temp-file rename, base64 Qt state), `restore()` (recreates widgets by id, calls `restoreState()`), `has_saved_layout()`. Format version 1 with compatibility check.
- `app/theme.py` — `apply_theme(app: QApplication)` + `_THEME` QSS string. Covers: QWidget, QMainWindow, QMenuBar, QMenu, QToolBar, QToolButton, QDockWidget, QTabBar, QTabWidget, QStatusBar, QPushButton, QLineEdit, QComboBox, QLabel, QScrollBar, QSplitter, QTreeView/QListView/QTableView, QHeaderView, QMessageBox, QCheckBox, QGroupBox, QToolTip.
- `widgets/watchlist/watchlist_widget.py` — `WatchlistWidget`: placeholder, self-registers as `"watchlist"` / `"Market Data"`.
- `widgets/chart/chart_widget.py` — `ChartWidget`: placeholder, self-registers as `"chart"` / `"Market Data"`.
- `widgets/order_entry/order_entry_widget.py` — `OrderEntryWidget`: placeholder, self-registers as `"order_entry"` / `"Orders"`.
- `widgets/positions/positions_widget.py` — `PositionsWidget`: placeholder, self-registers as `"positions"` / `"Orders"`.
- `tzdata>=2025.3` — Added to `pyproject.toml` (Windows has no OS timezone data; required by `zoneinfo.ZoneInfo`).
- `docs/widget_guide.md` — Full rewrite: complete example, lifecycle diagram, thread-safety pattern, broker call pattern, WidgetRegistry API, available widgets table.

### Changed
- `app/main_window.py` — Full rebuild. Toolbar (status dot, broker/client labels, IST clock, Add Widget button). File menu (Connect, Disconnect, Save Layout, Reset Layout, Exit). View menu (Add Widget by category, Save Layout). Help menu (About). `spawn_widget(widget_id, area)` — creates, sets `instance_id`, calls `addDockWidget`, connects `closed` signal. `remove_widget(instance_id)` — deregisters on close (deferred via `QTimer.singleShot(0,...)`). `on_login_success()` — restores saved layout or loads default. `_load_default_layout()` — watchlist left, chart+order_entry split horizontally right, positions bottom. `_restore_layout()` — delegates to `LayoutManager`, reconnects `closed` signals, updates instance counters. Auto-save every 3 min. `closeEvent` saves layout. Status bar shows last save time.
- `widgets/base_widget.py` — Added `closed = Signal()` (emitted in `closeEvent`), `instance_id: str = ""` attribute. Both needed by MainWindow for lifecycle management and layout persistence.
- `main.py` — Added `apply_theme(app)` call before `MainWindow` creation.
- `docs/architecture.md` — Updated layer diagram with WidgetRegistry, LayoutManager, theme. Updated module responsibility table.

### Architecture Decisions
- **Self-registration pattern**: widget modules call `WidgetRegistry.register()` at module level. `MainWindow` imports them with `# noqa: F401` to trigger registration — no hardcoded lists anywhere.
- **`instance_id = "{widget_id}_{n}"` per spawn**: supports multiple instances of the same widget type simultaneously (two charts, two watchlists). Counter tracked in `MainWindow._instance_counters`.
- **Deferred `remove_widget` via `QTimer.singleShot(0,...)`**: widget's `closeEvent` emits `closed`, which would call `remove_widget` synchronously if connected directly. Deferring to the next event loop iteration ensures `closeEvent` fully completes (incl. `super().closeEvent()`) before the widget is deregistered.
- **`LayoutManager` atomic save**: writes to `.json.tmp` then `os.replace()` — prevents corrupt layout.json on crash.
- **`LayoutManager.restore()` initial placement + `restoreState()`**: all restored widgets are initially added to `RightDockWidgetArea`, then `restoreState()` repositions them to their saved positions. Qt matches widgets by `objectName` (set to `instance_id`).
- **IST clock via `zoneinfo`**: uses `ZoneInfo("Asia/Kolkata")`. Required adding `tzdata` package — Windows has no system timezone data.
- **Global QSS via `apply_theme(app)`** before window creation: styles propagate to all child widgets automatically. Widget-level `setStyleSheet()` can layer overrides on top.

### Known Issues / TODOs
- Placeholder widgets show static labels — real implementations in Phase 5 (watchlist, order entry, positions) and Phase 6 (chart).
- `_load_default_layout()` uses `resizeDocks()` for size hints but Qt dock sizing is best-effort; actual sizes depend on window geometry at the time.
- Feed WebSocket still stubbed — `MarketFeed.connect()` logs a message (Phase 4).
- `widgets/order_book/`, `widgets/pnl/` folders exist but have no widget implementations yet.

---

## 2026-03-06 — Phase 2: Angel Broker Integration & Login Window

### Added
- `broker/angel_broker.py` — `AngelBroker(BaseBroker)`: full implementation wrapping `SmartApi` package. Covers connect (TOTP-based), disconnect, get_profile, get_holdings, get_positions, get_order_book, place_order, cancel_order, get_ltp, search_instruments (NSE/BSE/NFO/MCX), get_historical_data. Additional `get_feed_token()` for Phase 4.
- `app/main_window.py` — Real `MainWindow`: dock nesting enabled, dark QSS theme, File menu (Connect, Exit), View menu (Add Widget submenu placeholder), status bar (connection dot, broker name, client ID, clock), disconnected banner (hidden on login), `show_login()` + `on_login_success()` methods.
- `app/login_window.py` — `LoginWindow(QDialog)`: Mode A (full form — first launch) and Mode B (welcome back — returning launch). `_ConnectWorker(QThread)` runs `broker.connect()` off the main thread. Credential save/load from `config/settings.yaml` via `_save_credentials()` / `_load_saved_credentials()`. `login_successful(client_id, broker_name)` signal wired to `MainWindow.on_login_success()`.
- `docs/login_flow.md` — Login mode diagrams, worker thread pattern, startup sequence, credential storage format.
- `logzero>=1.7.0` — Added to `pyproject.toml` (transitive dependency required by `SmartApi` package).
- `websocket-client>=1.9.0` — Added to `pyproject.toml` (transitive dependency required by `SmartApi` package).

### Changed
- `broker/base_broker.py` — Added `BrokerAPIError(Exception)` class; all broker implementations raise this type so callers catch one exception.
- `broker/broker_manager.py` — Added `create_broker(broker_name, credentials)` factory method; instantiates and registers the named broker. Currently supports `"angel"`.
- `main.py` — Replaced bare Phase 1 placeholder window with real `MainWindow`; calls `show_login()` after `window.show()`; exits if login cancelled with no active connection.
- `docs/architecture.md` — Updated layer diagram to include `LoginWindow` and `MainWindow`; added their responsibilities to the module table.
- `docs/broker_api.md` — Added `BrokerAPIError` docs, `create_broker()` docs, `AngelBroker` credential dict, `get_feed_token()`, historical data intervals, updated rules.

### Architecture Decisions
- **`QDialog` for login, not `QDockWidget`**: login is a one-time modal flow, not a persistent dockable panel. `QDialog.exec()` blocks `show_login()` call naturally, making the startup sequence simple.
- **`QThread` subclass for connect worker** (not `QThreadPool`): connect is a single long-running operation with success/failure signals, not a pool task. `QThread` with explicit signals is cleaner for this pattern.
- **Mode A / Mode B via `QStackedWidget`**: single dialog with two pages avoids creating separate dialog classes. Pages share the same error label and title row.
- **`BrokerAPIError` as uniform exception type**: all broker SDK exceptions are caught internally and re-raised as `BrokerAPIError` so widget/login code never needs to import SmartApi exception types.
- **`SmartApi` module name**: the pip package is `smartapi-python` but the import is `SmartApi` (capital A). Also requires `logzero` and `websocket-client` as undeclared transitive deps — added to `pyproject.toml`.
- **`get_ltp` known limitation**: Angel's `ltpData` needs trading symbol as well as token; currently passes token as symbol. Real-time LTP will come from `MarketFeed` WebSocket in Phase 4.

### Known Issues / TODOs
- `get_ltp(exchange, token)`: passes token as tradingsymbol to Angel — works only if caller passes symbol name as token. Will be superseded by MarketFeed in Phase 4.
- `cancel_order`: defaults to `"NORMAL"` variety; bracket/cover order cancellation requires variety parameter — not exposed in `BaseBroker` interface yet.
- `place_order`: product type hardcoded to `"INTRADAY"` — needs to be parameterised in a future update.
- `app/widget_registry.py` — Widget registry not yet built (Phase 3).
- The dock area placeholder (`_dock_area`) is an empty QWidget — real dockable widgets come in Phase 3.

---

## 2026-03-06 — Phase 1: Project Scaffold & Core Infrastructure

### Added
- `pyproject.toml` — Project metadata, requires-python >=3.11, all runtime + dev dependencies declared
- `.python-version` — Pins Python 3.11 via uv
- `uv.lock` — Lockfile committed; use `uv sync` to reproduce environment on any machine
- `.gitignore` — Ignores `.venv/`, `__pycache__/`, `config/settings.yaml`, `logs/`, `config/layout.json`, cache dirs
- `config/settings.example.yaml` — Template for credentials; copy to `config/settings.yaml` and fill in values
- `utils/logger.py` — `get_logger(name)` + `configure_level(level_str)`; logs to console + rotating file (`logs/terminal.log`, 5MB × 3); creates `logs/` dir at runtime
- `utils/config.py` — `Config` singleton; dot-notation access e.g. `Config.get("broker.api_key")`; raises `FileNotFoundError` with helpful message if settings.yaml missing
- `models/instrument.py` — `Instrument` dataclass: symbol, token, exchange, name, instrument_type
- `models/tick.py` — `Tick` dataclass: token, exchange, ltp, open, high, low, close, volume, timestamp
- `models/order.py` — `Order` dataclass: order_id, symbol, exchange, side, order_type, quantity, price, status, timestamp
- `models/position.py` — `Position` dataclass: symbol, exchange, quantity, average_price, ltp, pnl
- `broker/base_broker.py` — `BaseBroker` ABC with full typed interface (connect, disconnect, get_profile, get_holdings, get_positions, get_order_book, place_order, cancel_order, get_ltp, search_instruments, get_historical_data)
- `broker/broker_manager.py` — `BrokerManager` singleton; `set_broker()` / `get_broker()`; raises RuntimeError if no broker set
- `feed/feed_models.py` — `SubscriptionMode` IntEnum: LTP=1, QUOTE=2, SNAP_QUOTE=3
- `feed/market_feed.py` — `MarketFeed` singleton; subscribe/unsubscribe with threading.Lock; `_on_tick()` dispatcher with per-callback exception handling; `connect()`/`disconnect()` are stubs (Phase 4)
- `widgets/base_widget.py` — `BaseWidget(QDockWidget)` ABC; `widget_id` class attr; abstract `on_show`, `on_hide`, `save_state`, `restore_state`; overrides showEvent/hideEvent/closeEvent
- `app/app_state.py` — `AppState` singleton; selected_instrument, is_connected with getters/setters
- `main.py` — Entry point: loads config log level, inits singletons, creates bare QMainWindow (1280×800), starts Qt event loop
- `app/__init__.py`, `broker/__init__.py`, `feed/__init__.py`, `widgets/__init__.py`, `models/__init__.py`, `utils/__init__.py` — Package markers
- `widgets/watchlist/__init__.py`, `widgets/chart/__init__.py`, `widgets/order_entry/__init__.py`, `widgets/order_book/__init__.py`, `widgets/positions/__init__.py`, `widgets/pnl/__init__.py` — Widget subpackage markers
- `docs/architecture.md` — Layer diagram, module responsibilities, data flow, singleton pattern, thread safety rules
- `docs/broker_api.md` — BaseBroker interface reference, BrokerManager usage, method table, rules
- `docs/market_feed.md` — subscribe/unsubscribe usage, thread safety pattern (Qt signal crossing), SubscriptionMode reference, Phase 1 stub status
- `docs/widget_guide.md` — How to add a widget, BaseWidget contract, lifecycle table

### Architecture Decisions
- **uv** chosen as package manager (over pip/poetry) per CLAUDE.md; `pyproject.toml` + `uv.lock` are the source of truth — no `requirements.txt`
- **Module-level singleton pattern** used for all singletons (BrokerManager, MarketFeed, AppState, Config) — avoids import-time side effects and is idiomatic Python
- **`config/settings.yaml` gitignored** — credentials never committed; `settings.example.yaml` is the committed template
- **Stub WebSocket** in Phase 1 — `connect()`/`disconnect()` log a message; `_on_tick()` is fully wired and ready for Phase 4 integration
- **`threading.Lock` in MarketFeed** — protects `_subscribers` dict against concurrent subscribe/unsubscribe from feed thread vs main thread

### Known Issues / TODOs
- `broker/angel_broker.py` — AngelBroker implementation not yet written (Phase 2)
- `app/main_window.py` — Real MainWindow with dock area and widget registry not yet built (Phase 3)
- `app/widget_registry.py` — Widget registry not yet built (Phase 3)
- `feed/market_feed.py` — WebSocket connection stubbed; real Angel WebSocket integration deferred to Phase 4
- Phase 1 window is a bare `QMainWindow` with title "Trading Terminal [Phase 1 — Scaffold]" — no widgets yet

---

## [Project Initialized]

### Architecture Decisions
- Widget-first design using PySide6 `QDockWidget` — every feature is an independent dockable widget
- Broker abstraction via `BaseBroker` ABC — current implementation is Angel SmartAPI, swappable without touching widgets
- Single WebSocket via `MarketFeed` singleton with pub/sub — widgets subscribe/unsubscribe, never open their own connections
- All cross-thread UI updates via Qt signals/slots — feed callbacks never touch widgets directly
- Layout persistence via `config/layout.json` using each widget's `save_state` / `restore_state`
- Config/secrets in `config/settings.yaml` (gitignored), template committed as `settings.example.yaml`

### Known Issues / TODOs
- Nothing built yet. Start with project scaffold.
