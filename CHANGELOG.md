# Changelog

---

## 2026-03-10 — Fix: FeedStatusWidget shows Disconnected while ticks are flowing

### Fixed
- `widgets/feed_status/feed_status_widget.py` — Race condition: `MarketFeed.connect()` is called before layout restore, so the WebSocket handshake can complete and `feed_connected` can be emitted **before** `FeedStatusWidget` exists and connects to the signal. Qt captures connected slots at emission time, so `FeedStatusWidget` missed the one-time `feed_connected` event. Ticks then flowed (widget was connected by then), causing the contradiction of "Disconnected" status + incrementing tick count. Fixed by checking `MarketFeed.instance().is_connected` immediately after wiring signals and calling `_on_connected()` synchronously if already live. Also added the same sync in `on_show()` so state is correct whenever the widget is re-shown.

### Architecture Decisions
- The pattern "connect signals, then read current state to sync" is the correct way to handle one-shot lifecycle signals on widgets created after the event fires. Applied here and should be the template for any future widget that displays feed connection state.

---

## 2026-03-10 — Fix: Watchlist REST snapshot populates LTP + prev_close after market hours

### Added
- `broker/base_broker.py` — new abstract method `get_quote(exchange, token) -> dict` returning `{"ltp": float, "prev_close": float}`.
- `broker/angel_broker.py` — implemented `get_quote` using Angel's `ltpData()` endpoint; extracts both `ltp` and `close` (prev day's close) from the response in one call.

### Changed
- `widgets/watchlist/watchlist_tab.py` — renamed `_LtpFetchWorker` → `_QuoteFetchWorker`; its `done` signal now carries `(token, ltp, prev_close)` instead of just `(token, ltp)`; `run()` calls `broker.get_quote()` instead of `broker.get_ltp()`. `_on_initial_ltp` updated to accept and forward both values.
- `widgets/watchlist/watchlist_model.py` — `update_initial_ltp` now accepts `prev_close` and writes it (with the `prev_close == 0` guard so a slow REST response cannot clobber a live-tick value). Change and chg_pct are computed immediately from the REST data, so after-hours watchlists display correct values on startup without needing any live tick.

### Architecture Decisions
- REST snapshot is the fallback source for both LTP and prev_close (runs on every symbol add and at startup for restored symbols). Live tick data takes precedence: the `prev_close == 0` guard in both `update_tick` and `update_initial_ltp` ensures whichever arrives first wins and subsequent calls are no-ops for that field.

---

## 2026-03-10 — Fix: Watchlist CHANGE / CHG% now uses previous day's close

### Fixed
- `feed/market_feed.py` — `_parse_tick` was only extracting `closed_price` in QUOTE/SNAP_QUOTE mode. Angel One sends it in LTP mode too. Moved `closed_price` parsing outside the mode guard so `Tick.close` is always populated, regardless of subscription mode.
- `widgets/watchlist/watchlist_model.py` — `update_tick`: added logic to capture `tick.close` as `row.prev_close` on the **first** tick for each symbol (`prev_close == 0` guard). This is never overwritten on subsequent ticks, making it a stable session reference. CHANGE and CHG% are now `LTP − prev_close` / `prev_close × 100` against the actual previous day's close, not the open.
- `widgets/watchlist/watchlist_model.py` — `update_initial_ltp`: removed incorrect `prev_close = ltp` assignment. Setting prev_close to today's LTP produced a false 0.00 change on add. Change/Chg% now display `—` until the first live tick arrives (which carries the real prev close).

### Architecture Decisions
- prev_close is sourced exclusively from `Tick.close` (i.e., `closed_price` in SmartWebSocketV2 binary frame) — this is the correct field per Angel One docs. No REST call is made for it.
- The "capture on first tick, never overwrite" pattern ensures the reference price stays stable all session even as LTP fluctuates.

---

## 2026-03-09 — UI: Consolidate status info into bottom status bar

### Changed
- `app/main_window.py` — Removed the top toolbar (`_setup_toolbar` and all `_tb_*` widgets). All status information is now in the bottom status bar only: connection dot → "Connected/Disconnected" → broker name → account ID → feed dot → "Feed: Live/—" → (right) HH:MM:SS IST clock. The "+ Add Widget" button was already in View → Add Widget; it remains there. Removed `QToolButton` import and the now-unused `_sb_save_time` / `_sb_instruments` labels and `_update_save_time()` helper.

---

## 2026-03-09 — Phase 8: Option Chain Widget

### Added
- `widgets/option_chain/__init__.py` — self-registers `OptionChainWidget` with `WidgetRegistry` under category "Market Data".
- `widgets/option_chain/option_chain_widget.py` — main `QDockWidget`; toolbar (underlying input, expiry combo, column selector, status label), underlying LTP bar, `QTableView` with two-row header. Uses `QRunnable` worker (`_ChainLoadWorker`) to fetch expiries + build chain + get underlying LTP off the main thread. Feed subscriptions via `subscribe_feed()` with `SNAP_QUOTE` for CE/PE tokens and `LTP` for the underlying.
- `widgets/option_chain/option_chain_model.py` — `OptionChainModel(QAbstractTableModel)` with `update_ce()`, `update_pe()`, `update_atm()` for incremental live updates; `OptionChainHeaderView(QHeaderView)` for two-row header (CALLS / PUTS group labels spanning CE/PE columns).
- `widgets/option_chain/option_chain_row.py` — `OptionChainRow` dataclass (strike, CE/PE fields: ltp, oi, oi_change, iv, delta, volume, is_atm flag).
- `widgets/option_chain/option_chain_builder.py` — `build_chain()`, `get_expiries()`, `get_atm_strike()` functions; directly iterates `InstrumentMaster._index` for full unfiltered scan. Expiry strings parsed via `datetime.strptime("%d%b%Y")` and sorted nearest first.
- `widgets/option_chain/iv_calculator.py` — Black-Scholes price, `calculate_iv()` (Newton-Raphson, up to 100 iterations, converges at `|diff| < 1e-6`), `calculate_delta()`. Uses `scipy.stats.norm.cdf`.
- `widgets/option_chain/column_selector_dialog.py` — `ColumnSelectorDialog(QDialog)`; grouped by CALLS / CENTER / PUTS sections; `ce_ltp`, `strike`, `pe_ltp` always-on; "Reset to Default" and "Apply" buttons; writes back to `ALL_COLUMNS` in-place and emits `columns_changed`.
- `docs/option_chain_widget.md` — full documentation for chain building, IV calculation, subscription strategy, two-row header, ATM computation, column visibility, and state persistence.
- `pyproject.toml` — added `scipy>=1.17.1` dependency via `uv add scipy`.

### Changed
- `main.py` — set application window icon from `icons/app_icon.png`.
- `app/main_window.py` — set window icon fallback from `icons/app_icon.png`.
- `docs/architecture.md` — added External Dependencies note for `scipy`.

### Architecture Decisions
- **Black-Scholes + Newton-Raphson for IV**: standard approach; converges in < 10 iterations for normal market conditions. Returns 0.0 on failure rather than raising, so a bad tick doesn't crash the table.
- **INDEX_TOKENS hardcoded dict**: Angel instrument master does not have a reliable way to identify index cash tokens from the options records. Hardcoding NIFTY=26000, BANKNIFTY=26009 etc. is the accepted practice. Stock options fall back to searching for `{NAME}-EQ` on NSE.
- **Direct `InstrumentMaster._index` scan** in `OptionChainBuilder`: the `search()` public API has a `max_results` cap and scoring that is unsuitable for exact-match bulk filtering. Direct access to the raw index list is intentional for this use case.
- **SNAP_QUOTE mode for CE/PE, LTP for underlying**: SNAP_QUOTE gives volume + OHLC which enables IV calculation; LTP is sufficient for the underlying price bar and ATM tracking.
- **Subscription limit guard at 950 tokens**: Angel limits to ~1000 active tokens per WebSocket session. With NIFTY having ~150 strikes = 300 tokens, this is generally safe. For wider underlyings, the guard restricts to ±50 strikes of ATM.
- **ATM recomputed on every underlying tick** (not throttled): acceptable since the model only emits `dataChanged` for background role, which is cheap.

### Known Issues / TODOs
- OI and OI Change always show `—` because `Tick` model and `MarketFeed._parse_tick()` do not yet extract `open_interest` / `open_interest_change` from the SNAP_QUOTE binary payload. Requires extending `models/tick.py` and `feed/market_feed.py`.
- BSE option chain (BFO exchange) not implemented.
- IV and Delta show `—` during non-market hours (LTP = 0 from feed). Expected behaviour.

---

## 2026-03-09 — Fix: place_order crash + defensive response parsing across all broker methods

### Fixed
- `broker/angel_broker.py` — `place_order()` crashed with `AttributeError: 'str' object has no attribute 'get'` because Angel SmartAPI occasionally returns a JSON *string* instead of a parsed dict. Fixed by introducing `_parse_response()` helper that detects a string response, attempts `json.loads()`, and raises `BrokerAPIError` with a clear message if the string is not valid JSON. Also fixed `order_id` extraction: `data` field can be a dict (`{"orderid": "..."}`) or a bare string (Angel sometimes returns the ID directly as the `data` value); both shapes are handled. Error path now includes the API `message` and `errorcode` fields in the exception message.
- `broker/angel_broker.py` — Applied the same `_parse_response()` defensive parsing to `get_order_book()`, `get_positions()`, `get_holdings()`, `cancel_order()`, and `get_profile()` — all were equally vulnerable to the string-response crash. All failure paths now log/raise the API's own `message` field instead of dumping the raw response object.

### Added
- `broker/angel_broker.py` — `_parse_response(resp, method_name) -> dict` private helper. Accepts any response object, normalises a string to dict via `json.loads`, rejects non-dict with a typed `BrokerAPIError`. Eliminates boilerplate type-checking from every individual method.
- `broker/angel_broker.py` — `logger.debug` in `place_order()` logs the raw response type and value immediately after the API call, before any parsing. Useful for diagnosing future response-format surprises.

### Architecture Decisions
- **Centralised response normalisation in `_parse_response`**: the string-vs-dict ambiguity is a library-level issue (SmartAPI library sometimes returns pre-parsed JSON, sometimes raw string depending on SDK version and endpoint). Centralising the fix means adding a new broker method in future only needs `self._parse_response(...)` and doesn't require re-discovering the pattern.
- **`order_id` extraction handles both dict and string `data`**: Angel docs show `data: {"orderid": "..."}` but in practice some API versions return `data: "<orderid>"` directly. Both shapes are extracted cleanly without a second crash.

---

## 2026-03-09 — Remove COVER variety + margin fetch debug & normalisation

### Changed
- `widgets/order_entry/order_form.py` — Removed COVER from the Variety toggle group. Buttons are now only `NORMAL` and `BRACKET`. Removed `is_cover` logic and COVER-specific trigger-field visibility from `_on_variety_changed()`. Removed "COVER" from `variety_map` in both `get_order_params()` and `_get_margin_params()`. Trigger row is now only shown for SL/SL-M order types. Saved layouts that previously stored variety="COVER" will silently fall back to NORMAL on restore.
- `broker/angel_broker.py` — Removed COVER guard from `get_order_margin()` (no longer needed since the UI doesn't offer COVER). Added explicit price normalisation for non-MARKET orders: price is now formatted as `f"{float(price):.2f}"` (clean 2-decimal string). Improved failure logging: on `status=False` response, logs the API `message` field at WARNING level rather than raising a generic string. Improved debug logging: logs outgoing params and the full raw response at DEBUG level to assist diagnosis when margin shows `—`.

### Debug scaffolding (temporary — remove once margin is confirmed working)
- `widgets/order_entry/order_form.py` — `_start_margin_fetch()` now logs `"Margin fetch triggered"` at DEBUG to confirm the debounce timer is firing. Check `logs/terminal.log` after changing qty or price with an instrument selected.
- `broker/angel_broker.py` — `get_order_margin()` logs `"sending params=..."` and `"raw response=..."` at DEBUG. These lines reveal the exact request and Angel API response for diagnosis.

### Architecture Decisions
- **COVER removed, not hidden**: Angel's COVER (CO) variety requires a trigger price and has strict INTRADAY-only constraints that created confusing interactions. Removing it from the UI eliminates an entire class of AB4033 errors at the source. If COVER support is needed in the future it can be re-added as its own dedicated form section.
- **Price normalised in broker layer**: `f"{float(price):.2f}"` avoids sending `"1600.0"` or `"1600"` for limit prices. Angel's margin API has been observed to reject `"0.0"` for MARKET and is strict about number formats; ensuring a consistent 2-decimal string for all non-MARKET orders is the safest default.

---

## 2026-03-09 — Fix: AB4033 margin API validation + N/A display + font warning

### Fixed
- `broker/angel_broker.py` — `get_order_margin()`: Added pre-call validation guards. COVER variety is only valid with INTRADAY product type; BRACKET/ROBO is only valid with INTRADAY. If the combination is invalid, returns `0.0` immediately without calling the API (was previously sending the call and getting AB4033 Invalid Request). Also normalises MARKET order price to `"0"` (not `"0.0"`) and quantity to a plain integer string. Added `logger.debug` before the API call and for the raw response for easier future debugging.
- `widgets/order_entry/order_form.py` — `_on_margin_done()`: now shows `"N/A"` in muted colour when margin returns `<= 0.0`. Previously showed `"₹0.00"` which was confusing when the combination was invalid or API returned zero.
- `widgets/order_entry/order_form.py`, `widgets/watchlist/watchlist_tab.py`, `widgets/watchlist/add_manual_dialog.py` — All `_Signals` inner classes changed from `QWidget` to `QObject`. Using `QWidget` as a signal carrier was causing Qt to process a full widget font stack on instantiation; when the application stylesheet uses pixel-based font sizes, Qt's font system internally holds `pointSize == -1` which triggered the `QFont::setPointSize: Point size <= 0 (-1)` warning seen in logs. `QObject` carries signals identically without any UI overhead.

### Architecture Decisions
- **Return `0.0` (not raise) for invalid variety+product combos**: The margin display is informational — it should silently show "N/A" rather than flashing an error for a combination the user may be in the middle of changing. The validation is in the broker layer so it works for any future caller too.
- **Normalise price/quantity in broker layer, not form**: The form already passes sensible values, but the broker layer is the authoritative place to enforce API wire format constraints (integer quantity strings, `"0"` not `"0.0"` for MARKET). This prevents the same mistake if `get_order_margin` is called from other places in the future.

---

## 2026-03-09 — Fix: order margin API method name and batch wrapper

### Fixed
- `broker/angel_broker.py` — `get_order_margin()` was calling `self._smart.orderMargin()` which does not exist on `SmartConnect`. The actual library method is `self._smart.getMarginApi()`. Additionally, the endpoint (`/margin/v1/batch`) is a batch API — it requires the params wrapped as `{"orders": [margin_params]}` and returns `data` as a list. Fixed both: now calls `getMarginApi({"orders": [margin_params]})` and unwraps the first element of the `data` list before reading the margin value. Added handling for both list and dict response shapes defensively.

---

## 2026-03-09 — Order Entry: LTP pre-fill + margin required display

### Changed
- `widgets/order_entry/order_form.py` —
  **Fix 1 (LTP pre-fill):** Added `_current_ltp: float = 0.0` state variable, set in `_on_ltp_main()` on every tick. `_on_order_type_changed()` now pre-fills `_price_spin` with `_current_ltp` when switching to LIMIT or SL, but only if `_price_spin.value() == 0.0` (never overwrites a user-entered price). SL / SL-M also pre-fill `_trigger_spin` from `_current_ltp` if trigger is currently 0. MARKET and SL-M still clear and disable the price field. `_on_variety_changed()` similarly pre-fills the trigger when switching to COVER variety.
  **Fix 2 (Margin row):** Added `_MarginWorker(QRunnable)` with inner `_Signals(QWidget)` for result/failure signals (consistent with existing worker pattern). Added `_margin_timer: QTimer` (600 ms single-shot debounce). Added `_margin_value: QLabel` displayed between the LTP row and the Place Order button. `_schedule_margin_fetch()` resets the debounce timer; `_start_margin_fetch()` builds params via `_get_margin_params()` and launches the worker. On success: shows `₹{margin:,.2f}` in white monospace. On failure: shows `—` in muted color; error logged at DEBUG level only. All form field changes (side, order type, product type, variety, qty, price) call `_schedule_margin_fetch()`. `set_instrument()` immediately shows "Calculating…" and schedules a fetch. If qty is 0 or no instrument is selected, shows `—` without launching a worker.

- `broker/base_broker.py` — Added abstract method `get_order_margin(margin_params: dict) -> float`. Keys: `exchange`, `tradingsymbol`, `symboltoken`, `transactiontype`, `ordertype`, `producttype`, `variety`, `quantity` (str), `price` (str). Raises `BrokerAPIError` on failure.

- `broker/angel_broker.py` — Implemented `get_order_margin()` via `SmartConnect.orderMargin()`. Handles multiple possible response shapes for `data`: numeric string, dict with `netMargin` / `totalMarginRequired` / `marginRequired` / `margin` key, or first numeric value in dict. Raises `BrokerAPIError` if the response is non-OK or the margin value cannot be extracted.

### Architecture Decisions
- **Debounce timer on qty/price changes**: `QSpinBox.valueChanged` fires on every arrow-key or keyboard press. A 600 ms single-shot timer (reset on every signal) prevents a REST call per keystroke. All other toggles (side, order type, product, variety) fire immediately on click so they feel responsive.
- **`_current_ltp` stored on form, not fetched on demand**: LTP is already arriving via `MarketFeed` ticks on every update. Storing the last-seen value as `float` is zero-cost and avoids a REST call just to pre-fill a field.
- **Pre-fill guard `value() == 0.0`**: only pre-fills when the field is blank/zero. If the user has already typed a price and switches order type (e.g. LIMIT → SL), their price is preserved.
- **`_MarginWorker` uses `QRunnable` + `_Signals(QWidget)` pattern**: consistent with `_LtpFetchWorker` in `watchlist_tab.py`. `QRunnable` is pool-managed (no explicit thread lifecycle). `_Signals` must be created on the main thread (done in `__init__` before `start()`), satisfying Qt's `QObject` thread-affinity requirement.
- **`_get_margin_params()` returns `None` when qty == 0**: avoids a pointless API call immediately after form load. The worker is never launched; the margin row shows `—`.

---

## 2026-03-09 — UI Polish: Custom dock title bar (float + close buttons)

### Changed
- `widgets/base_widget.py` — Added `BaseWidgetTitleBar(QWidget)` class with signals `close_clicked` and `float_clicked`. Custom title bar layout: title label (bold, `#e6edf3`, stretches left) → ⧉ float button → ✕ close button. Both buttons 20×20 px, flat, transparent background. Close button hover: `#3a1a1a` background, `#f85149` text. Float button hover: `#1a2a3a` background, `#1f6feb` text. Float button turns accent-colored when the widget is floating. Title bar background `#1f2937`, fixed height 28 px. QSS scoped via `setStyleSheet` on the title bar widget so rules do not leak into content. `BaseWidget.__init__()` now: sets `DockWidgetMovable | DockWidgetFloatable | DockWidgetClosable` features, installs `BaseWidgetTitleBar` via `setTitleBarWidget()`, connects `close_clicked → self.close()` and `float_clicked → self._toggle_float()`, connects `topLevelChanged → _on_float_state_changed()`. Added `_toggle_float()` and `_on_float_state_changed()` methods. All existing and future widgets inherit the title bar automatically — no subclass changes required.

### Architecture Decisions
- **Single file change for all widgets**: title bar is installed in `BaseWidget.__init__()` so every existing widget (Watchlist, Chart, Order Entry, Positions, Feed Status) and every future widget gets it automatically without any per-widget changes.
- **`setTitleBarWidget()`**: replaces Qt's default title bar. The default bar is removed entirely; our custom bar handles all interactions (drag, float, close). Qt still provides the drag-to-dock behaviour because the widget is still a `QDockWidget`.
- **`set_float_active()` object name swap + `unpolish/polish`**: changing `objectName` alone does not trigger a QSS re-evaluation mid-run. Calling `style().unpolish()` then `style().polish()` forces Qt to re-apply the stylesheet for the updated object name, giving immediate visual feedback when the widget is floated or re-docked.
- **QSS scoped to title bar**: `setStyleSheet(_TITLEBAR_QSS)` is called on `BaseWidgetTitleBar` itself, not on `BaseWidget`. This constrains the button rules to the title bar widget subtree and prevents them from overriding button styles in content widgets (e.g. `OrderForm`'s BUY/SELL buttons).
- **`DockWidgetFeatures` explicitly set**: ensures the dock is movable, floatable, and closable regardless of any platform or Qt-version default differences. Previously unset — now guaranteed in `BaseWidget`.

---

## 2026-03-09 — Phase 7: Order Entry & Positions/P&L Widgets

### Added
- `widgets/order_entry/order_form.py` — `OrderForm(QWidget)`: full embedded order entry form. BUY/SELL toggle (colored), symbol search (reuses `SearchDialog`), Order Type toggle group (MARKET/LIMIT/SL/SL-M), Product toggle (INTRADAY/DELIVERY), Variety toggle (NORMAL/BRACKET/COVER). Dynamic field visibility: price disabled for MARKET/SL-M, trigger shown for SL/SL-M/COVER, bracket block shown only when BRACKET selected. Inline validation with red error label. `get_order_params()` returns Angel SmartAPI `placeOrder` dict. LTP label updated via `MarketFeed` (feed thread → `_ltp_signal` → main thread). `save_state()`/`restore_state()` for side, order type, product, variety, instrument.
- `widgets/order_entry/order_confirmation_dialog.py` — `OrderConfirmationDialog(QDialog)`: pre-trade confirmation popup. Shows side, qty, symbol, exchange, order type+price, product type. Confirm button colored by side (green/red). Not dismissable by clicking outside (`ApplicationModal`). Returns `Accepted`/`Rejected`.
- `widgets/positions/positions_model.py` — `PositionsModel(QAbstractTableModel)`: 8 columns (Symbol, Exch, Qty, Avg Price, LTP, Unrealized P&L, Realized P&L, Total P&L). P&L columns colored green/red/muted by sign. `update_ltp()` emits targeted `dataChanged` for a single row. `set_positions()` does full reset. `get_totals()` for summary bar.
- `widgets/positions/trades_model.py` — `TradesModel(QAbstractTableModel)`: 7 columns (Time, Symbol, Side, Qty, Price, Product, Status). Side colored green/red. Status colored by value. Sorted newest-first. `set_orders()` full reset.
- `widgets/positions/pnl_summary.py` — `PnLSummary(QFrame)`: compact bar showing Realized / Unrealized / Total / Position count, each colored by sign. `update()` refreshes all labels.
- `docs/order_entry_widget.md` — documents order type visibility rules, validation logic, Angel API parameter mapping, and watchlist → order entry integration.
- `docs/positions_widget.md` — documents live P&L formulas, feed subscription lifecycle, periodic refresh merge strategy, and order placed → positions refresh flow.

### Changed
- `models/order.py` — full rewrite: all fields default to zero/empty (no required positional args). Added: `token`, `product_type`, `variety`, `trigger_price`, `squareoff`, `stoploss`, `trailing_stoploss`, `status_message`, `filled_quantity`, `average_price`. Removed: positional required fields (backward-compatible construction still works for named kwargs).
- `models/position.py` — full rewrite: all fields default to zero/empty. Added: `token`, `product_type`, `overnight_quantity`, `buy_quantity`, `sell_quantity`, `buy_average`, `sell_average`, `close_price`, `unrealized_pnl`, `realized_pnl`, `total_pnl`. Removed: `pnl` (replaced by the three computed fields).
- `broker/base_broker.py` — `place_order(instrument, side, order_type, quantity, price)` signature replaced with `place_order(order_params: dict)`. Accepts raw Angel API parameter dict. Documented required and optional keys.
- `broker/angel_broker.py` — `place_order()` now passes `order_params` directly to `placeOrder()`. `get_positions()` maps all new `Position` fields from the response (token, product_type, overnight_qty, buy/sell quantities, averages, close_price, computed unrealized_pnl). `get_order_book()` maps all new `Order` fields (token, product_type, variety, trigger_price, status_message, filled_quantity, average_price). `get_holdings()` updated to new `Position` constructor (product_type="DELIVERY").
- `widgets/order_entry/order_entry_widget.py` — full rewrite of placeholder. Embeds `OrderForm`. `_PlaceOrderWorker(QThread)` runs `place_order()` off the main thread. Status bar shows success (green, order ID) or failure (red, error). `order_placed = Signal(str)` emitted on success. `set_instrument()` unsubscribes previous feed and re-subscribes new. `on_show()` re-subscribes current instrument. `save_state()`/`restore_state()` delegates to `OrderForm`.
- `widgets/positions/positions_widget.py` — full rewrite of placeholder. `_PositionsWorker(QThread)` fetches positions and order book. Live LTP via `subscribe_feed()` per open position. 30-second `QTimer` auto-refresh. `refresh()` public method for external trigger. `PnLSummary` updated after every LTP tick.
- `widgets/watchlist/watchlist_tab.py` — added `instrument_selected = Signal(object)` emitted on row double-click. Added `_on_row_double_clicked()` handler.
- `widgets/watchlist/watchlist_widget.py` — added `instrument_for_order_entry = Signal(object)` relayed from each tab's `instrument_selected`. Connected in `_create_tab()`.
- `app/main_window.py` — added `send_instrument_to_order_entry()`, `_on_order_placed()`. `spawn_widget()` now connects `instrument_for_order_entry` for watchlist widgets and `order_placed` for order_entry widgets. `_restore_layout()` applies the same wiring for restored widgets.
- `docs/architecture.md` — added "Inter-Widget Communication" section documenting the watchlist → order entry and order placed → positions refresh patterns.

### Architecture Decisions
- **`BaseBroker.place_order(order_params: dict)`**: changed from a narrow 5-arg signature to a raw dict pass-through. Rationale: the form needs to express bracket orders, SL orders, AMO, etc. — a fixed signature cannot capture all cases cleanly without an explosion of optional parameters. The dict matches Angel's `placeOrder` format directly. A future broker abstraction can define a translator layer inside its own `place_order()` if needed.
- **`Position` / `Order` all-defaults dataclass**: making all fields default to zero/empty avoids positional-argument fragility when new fields are added. Construction remains concise with named kwargs.
- **Full reset on 30-second positions refresh**: chosen over a merge strategy. Retail traders have <50 positions; `beginResetModel/endResetModel` at 30-second intervals has no visible cost. Simplicity > optimisation here.
- **`_PositionsWorker` fetches positions and orders in the same thread run**: one worker, two sequential REST calls. Keeps the code simple and avoids race conditions between the two fetches.
- **Watchlist → Order Entry via `MainWindow` relay**: widgets never hold references to siblings. All cross-widget routing is through `MainWindow` methods, consistent with existing watchlist → chart integration.
- **`OrderForm._ltp_signal` (private `Signal`)**: `OrderForm` is a plain `QWidget`, not a `BaseWidget`, so it cannot use `subscribe_feed()`. The feed callback (`ltp_feed_callback`) is called on the feed thread and immediately emits `_ltp_signal` to cross to the main thread safely. The subscription is owned by `OrderEntryWidget` (which IS a `BaseWidget`) so `_unsubscribe_all_feeds()` handles cleanup.

### Known Issues / TODOs
- AMO (After Market Order) variety not exposed in the Order Entry UI. Add `"AMO"` to variety buttons when needed.
- `TradesModel` shows all orders. Filtering to `status == "COMPLETE"` only requires a single-line change in `_on_orders_ready`.
- Angel position response does not always return `symboltoken` — positions without a token will not receive live LTP updates (they will show the snapshot LTP from the REST response only).
- `BaseBroker.cancel_order()` still defaults to "NORMAL" variety — bracket/cover order cancellation needs a variety parameter in a future update.

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
