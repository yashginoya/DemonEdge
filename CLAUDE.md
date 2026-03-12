# CLAUDE.md — Trading Terminal Project Instructions

## Project Overview

A Python-based desktop trading terminal for Windows/Linux built with **PySide6**. The terminal is fully widget-based — every feature is an independent, dockable `QDockWidget`. New features are added as new widgets or updates to existing ones. The architecture is designed for extensibility, maintainability, and live trading performance.

---

## Core Architecture Principles

### 1. Widget-First Design
- Every feature (chart, order book, order entry, watchlist, option chain, PnL, logs, analytics, etc.) is a `QDockWidget` subclass.
- Widgets are **self-contained**: each widget manages its own UI, internal state, and data subscriptions.
- Widgets are **independent**: one widget crashing or hanging must not affect others.
- The main window (`MainWindow`) is purely a shell — it holds the dock area, menu bar, and the widget registry. It has no business logic.
- New features = new widget files. No feature logic goes into `MainWindow`.

### 2. Broker API Abstraction Layer
- **Never** call any broker SDK (e.g., Angel SmartAPI) directly from widgets or anywhere outside the broker layer.
- All broker interactions go through `broker/base_broker.py` — an abstract base class (`BaseBroker`) that defines the interface.
- The current broker implementation (`broker/angel_broker.py`) extends `BaseBroker` and wraps Angel SmartAPI calls.
- To switch brokers in the future: implement a new class extending `BaseBroker`. No widget code changes.
- `BaseBroker` must define all methods that any part of the app may call: `get_profile()`, `get_holdings()`, `get_positions()`, `place_order()`, `cancel_order()`, `get_order_book()`, `get_ltp()`, `search_instruments()`, `get_historical_data()`, etc.
- The active broker instance is managed by a `BrokerManager` singleton, accessible app-wide.

### 3. Single WebSocket Feed (Market Data Bus)
- There is **one and only one** WebSocket connection to the broker for live tick data — `feed/market_feed.py`.
- `MarketFeed` is a singleton that manages the WebSocket lifecycle (connect, reconnect, heartbeat).
- Widgets **never** open their own WebSocket connections.
- Widgets subscribe to symbols via the `MarketFeed` pub/sub interface: `market_feed.subscribe(symbol, callback)` and `market_feed.unsubscribe(symbol, callback)`.
- `MarketFeed` internally maintains a subscriber map: `{symbol: [list of callbacks]}`. On tick receipt, it dispatches to all registered callbacks for that symbol.
- All tick callbacks are invoked on the feed thread. Widgets must use Qt signals to push data to the UI thread — **never update UI directly from a non-Qt thread**.
- When a widget is closed/hidden, it must unsubscribe all its symbols.

### 4. Thread Safety
- All UI updates must happen on the **Qt main thread**.
- Background tasks (REST API calls, historical data fetches, computations) run in `QThreadPool` workers or `QThread` subclasses.
- Use Qt signals/slots for cross-thread communication — never manipulate Qt widgets from worker threads.
- Use Python's `threading.Lock` or `queue.Queue` where shared state is accessed from multiple non-Qt threads (e.g., inside `MarketFeed`).

---

## Project Structure

```
trading_terminal/
│
├── CLAUDE.md                         ← This file
├── CHANGELOG.md                      ← Session history (Claude maintains this)
├── main.py                           ← Entry point
├── pyproject.toml                    ← Project metadata + dependencies (uv)
├── uv.lock                           ← Lockfile — committed to version control
├── .python-version                   ← Pins Python version for uv
├── .gitignore
│
├── docs/                             ← Documentation (Claude maintains this)
│   ├── architecture.md
│   ├── broker_api.md
│   ├── market_feed.md
│   ├── widget_guide.md
│   └── ...
│
├── app/
│   ├── main_window.py                ← MainWindow shell, dock area, widget registry
│   ├── widget_registry.py            ← Registry of all available widgets
│   └── app_state.py                  ← Global app state (selected instrument, session info, etc.)
│
├── broker/
│   ├── base_broker.py                ← Abstract base class (interface definition)
│   ├── angel_broker.py               ← Angel SmartAPI implementation
│   └── broker_manager.py             ← Singleton managing the active broker instance
│
├── feed/
│   ├── market_feed.py                ← Singleton WebSocket feed manager + pub/sub
│   └── feed_models.py                ← Tick data models / dataclasses
│
├── widgets/
│   ├── base_widget.py                ← Base class for all dock widgets
│   ├── watchlist/
│   │   ├── watchlist_widget.py
│   │   └── ...
│   ├── chart/
│   │   ├── chart_widget.py
│   │   └── ...
│   ├── order_entry/
│   │   ├── order_entry_widget.py
│   │   └── ...
│   ├── order_book/
│   ├── positions/
│   ├── pnl/
│   └── ...                           ← Each new feature is a new folder here
│
├── models/                           ← Shared data models / dataclasses
│   ├── instrument.py
│   ├── order.py
│   ├── position.py
│   └── tick.py
│
├── utils/
│   ├── logger.py                     ← Centralized logging setup
│   ├── config.py                     ← Config loader (API keys, settings)
│   └── ...
│
└── config/
    ├── settings.yaml                 ← App configuration
    └── layout.json                   ← Saved dock layout
```

---

## Development Rules

### Package Management
- This project uses `uv` for package management — never use `pip install` directly.
- The virtual environment lives at `.venv/` in the project root (created by `uv`).
- Dependencies are declared in `pyproject.toml`. `uv.lock` is committed to version control so any machine gets identical installs.
- To add a dependency: `uv add <package>`. To remove: `uv remove <package>`.
- To run the app: `uv run python main.py` (or activate `.venv` first).
- To install all deps on a new machine: `uv sync`.
- Never commit `.venv/` — it is in `.gitignore`.
- `requirements.txt` is not used. `pyproject.toml` + `uv.lock` are the source of truth.

## Git Rules

**Claude must NEVER run any git command autonomously.** No exceptions.

This means never run: `git add`, `git commit`, `git push`, `git pull`, `git fetch`, `git merge`, `git rebase`, `git stash`, `git checkout`, `git branch`, `git reset`, `git revert`, or any other git subcommand — unless explicitly instructed to do so in the current message.

The only git-related actions Claude may take without being asked are read-only status checks: `git status`, `git log`, `git diff` — and only when directly relevant to understanding a problem.

**Why this rule exists**: The developer controls when code is committed and pushed. Claude committing or pushing unreviewed work bypasses that control entirely.

If Claude thinks something is worth committing (e.g. after completing a phase), it should say: "This looks like a good point to commit — let me know if you'd like me to stage and commit the changes." Then wait for explicit confirmation before touching git.

**Commit Messages**: Never add `Co-Authored-By`, `Co-authored-by`, or any similar trailer lines to commit messages. Commit messages must contain only the subject line and optional body — no attribution footers of any kind.

---

### Adding a New Widget

1. Create a new folder under `widgets/` named after the feature.
2. The main widget class must subclass `BaseWidget` (which subclasses `QDockWidget`).
3. Register it in `widget_registry.py`.
4. The widget appears in the terminal's **View → Add Widget** menu automatically via the registry.
5. Write a brief doc entry in `docs/widget_guide.md` for the new widget.

### `BaseWidget` Contract
Every widget must:
- Call `super().__init__()` correctly.
- Implement `on_show()` — called when widget becomes visible (subscribe to feeds here).
- Implement `on_hide()` — called when widget is hidden (unsubscribe from feeds here).
- Implement `save_state() -> dict` — returns serializable state for layout persistence.
- Implement `restore_state(state: dict)` — restores widget from saved state.
- Never directly reference `AngelBroker` or any concrete broker class — only use `BrokerManager.get_broker()`.

### Broker API Rules
- `BaseBroker` is the **only** interface used outside `broker/`.
- All methods in `BaseBroker` are abstract. If a broker doesn't support a method, it raises `NotImplementedError` with a clear message.
- Broker calls that involve I/O must be run in a worker thread, not the Qt main thread.
- Authentication/session management is handled inside the broker implementation, not by callers.

### MarketFeed Rules
- The canonical feed interface is `BaseFeed` (`feed/base_feed.py`). The active implementation is accessed via `FeedManager.get_feed()` (`feed/feed_manager.py`). **Never import or call `AngelFeed` or `MarketFeed` directly outside of `feed/`.**
- Subscribe: `FeedManager.get_feed().subscribe(exchange, token, callback)`.
- Unsubscribe: `FeedManager.get_feed().unsubscribe(exchange, token, callback)`.
- `callback(tick: Tick)` is called from the feed thread — widget must re-emit via Qt signal.
- `FeedManager` lazy-initialises the default `AngelFeed` if no feed has been explicitly set — just calling `FeedManager.get_feed()` is always safe.
- `MarketFeed` (module-level alias in `feed/market_feed.py`) is kept for backward compatibility only. New code must use `FeedManager.get_feed()`.
- The feed handles reconnection internally. Widgets do not need to handle feed disconnects.

### Coding Standards
- Python 3.11+.
- Type hints on all function signatures.
- Dataclasses for all data models (`@dataclass`).
- No global mutable state outside of explicit singletons (`BrokerManager`, `FeedManager`, `AppState`).
- All singletons implemented with `__new__`-based or module-level singleton pattern, not bare globals.
- Use `logging` (from `utils/logger.py`) — never use `print()` for anything except debug throwaway code.
- Format with `black`. Lint with `ruff`.
- Keep widget files focused: UI setup in `__init__`, subscriptions in `on_show`, logic in private methods.

### Configuration
- API credentials and broker config go in `config/settings.yaml` (never hardcoded).
- `config/settings.yaml` is in `.gitignore`. A `config/settings.example.yaml` template is committed.
- `utils/config.py` provides a `Config` singleton for reading settings.

### Layout Persistence
- On app exit, `MainWindow` serializes dock layout + each widget's `save_state()` to `config/layout.json`.
- On startup, layout is restored from `layout.json` if it exists.

### Naming Conventions

#### Application Name
- The application is named **DemonEdge**. Do not use "Trading Terminal" anywhere in user-visible text.

#### Window Title Convention
- The main window title is exactly `"DemonEdge"` — no suffix.
- **Standalone secondary windows** (`QWidget` with `Qt.WindowType.Window` flag, or `QMainWindow`) must use the format `"DemonEdge - <Window Name>"`.
  - Examples: `"DemonEdge - Log Viewer"`, `"DemonEdge - Connect to Broker"`.
- **`QDialog` subclasses** must use a short descriptive title only — **do not** apply the `"DemonEdge - "` prefix to dialogs.
  - Examples: `"Strike Settings"`, `"Column Visibility"`, `"Add Instrument"`, `"Confirm Order"`.
- The distinction: standalone windows live in the taskbar / OS window list and need the app name for context; dialogs are always parented to a window and their title is already contextual.

#### Command Palette
- The Command Palette (`app/command_palette.py`, `CommandPalette`) is opened via **Ctrl+K** or the **⌘ Widgets** button in the status bar.
- It is the primary way to add widgets. Any widget registered in `WidgetRegistry` is automatically discoverable — no extra registration needed.
- `WidgetDefinition` has an optional `description: str = ""` field. Set it when registering a widget to provide a one-line description shown in the palette. Falls back to the widget's `category` if omitted.
- The palette is a `Qt.WindowType.Tool | FramelessWindowHint` top-level window parented to `MainWindow`. It auto-dismisses on window deactivate (click outside), Escape, or after a selection.

#### Keyboard Shortcuts Convention
- All keyboard shortcuts in DemonEdge must be registered in **two places simultaneously**:
  1. As a `QShortcut` in `MainWindow._register_shortcuts()` (`app/main_window.py`).
  2. As an entry in `_SECTIONS` inside `app/shortcuts_dialog.py` — this populates the **Help → Keyboard Shortcuts** window (`Ctrl+/`), which is the single source of truth for what shortcuts exist.
- Never add a shortcut without updating both. Never list a shortcut in the window that is not actually registered, and vice versa.
- The `_register_shortcuts()` method is the only place global shortcuts should be created. Do not scatter `QShortcut` instantiation across `__init__` or other methods.
- The Keyboard Shortcuts window (`KeyboardShortcutsWindow`) is a persistent non-modal `QWidget(None, Qt.Window)` — independent of the main window, stays visible when the terminal loses focus, hides on close (does not destroy). Open via `Ctrl+/` or Help → Keyboard Shortcuts.

---

## Documentation (`docs/`)

Claude must keep the `docs/` folder updated. After implementing or significantly modifying any module:

| File | Update when |
|---|---|
| `docs/architecture.md` | Any structural change to modules, layers, or data flow |
| `docs/broker_api.md` | Any change to `BaseBroker`, `BrokerManager`, or a broker implementation |
| `docs/market_feed.md` | Any change to `MarketFeed`, subscription interface, or tick models |
| `docs/widget_guide.md` | Any new widget added or widget interface changed |

Docs are written in Markdown, concise, with code examples where relevant. They are reference material for future development sessions.

---

## Technology Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| UI Framework | PySide6 |
| Docking | `QDockWidget` (native PySide6) |
| Broker | Angel SmartAPI (via abstraction layer) |
| Live Feed | Angel WebSocket (via `MarketFeed` singleton) |
| Charts | TBD (pyqtgraph preferred for performance) |
| Config | PyYAML |
| Logging | Python `logging` |
| Package Manager | `uv` (with virtual environment and lockfile) |

---

## Current Broker: Angel SmartAPI

- Library: `smartapi-python`
- Auth: TOTP-based. Credentials from `config/settings.yaml`.
- WebSocket class: `SmartWebSocket` from the library — wrapped inside `MarketFeed`.
- REST calls: wrapped inside `AngelBroker(BaseBroker)`.
- Docs: https://smartapi.angelbroking.com/docs

---

## Out of Scope (for now)

- Multi-broker simultaneous connections.
- Cloud sync of layouts or strategies.
- Mobile UI.

These may be added later as widgets or broker implementations — the architecture supports them.

---

## Notes for Claude

- **At the start of every session: read `CHANGELOG.md` first.** This is the single source of truth for what has been built. Do not ask Yash what was done before — read the changelog.
- Before starting a task, re-read relevant `docs/` entries to stay aligned with prior decisions.
- After completing a task, update the relevant `docs/` entries.
- **After completing a task: update `CHANGELOG.md`.** This is mandatory, not optional.
- When in doubt about where code belongs, refer to the layering rules: broker stuff → `broker/`, feed stuff → `feed/`, UI stuff → `widgets/`, shared models → `models/`.
- Prefer extending `BaseWidget` / `BaseBroker` over modifying `MainWindow` or `MarketFeed` core logic.
- Keep `main.py` minimal — it initializes singletons, creates `MainWindow`, starts the Qt event loop.

---

## CHANGELOG.md — Format & Rules

The `CHANGELOG.md` file lives at the project root alongside `CLAUDE.md`. Claude is solely responsible for keeping it updated.

### When to update
- After completing any task, feature, or fix — no matter how small.
- After any structural/architectural decision is made (even if no code was written).
- After any existing module is meaningfully refactored.

### Format

```markdown
# Changelog

## [Unreleased]
- Work in progress items go here (if any mid-session incomplete work)

---

## YYYY-MM-DD — <Short session title>

### Added
- `broker/base_broker.py` — Abstract BaseBroker with full interface definition
- `feed/market_feed.py` — MarketFeed singleton with pub/sub and auto-reconnect

### Changed
- `widgets/base_widget.py` — Added `save_state` / `restore_state` contract

### Fixed
- Feed thread was not releasing lock on disconnect — fixed in `market_feed.py`

### Architecture Decisions
- Decided to use pyqtgraph over matplotlib for chart widget (performance reason)

### Known Issues / TODOs
- Order entry widget: bracket order support not yet implemented
- Historical data fetch: pagination not handled for large date ranges
```

### Rules
- Each entry is dated. Use `YYYY-MM-DD` format.
- List every file touched, with a one-line description of what changed and why.
- **Architecture Decisions** section: log any non-obvious choices made (library picks, pattern choices, tradeoffs). This prevents re-debating decisions in future sessions.
- **Known Issues / TODOs**: log anything deferred or incomplete. This replaces the need for Yash to remember and re-explain unfinished work.
- Entries are newest-first (most recent at top).
- Do not delete old entries. The full history must be preserved.