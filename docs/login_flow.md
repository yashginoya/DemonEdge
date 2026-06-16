# Login Flow

## Overview

The terminal always opens in a **disconnected state** with a visible banner. The `LoginWindow` appears as a modal dialog on top of `MainWindow` immediately at startup. Once login succeeds, the banner disappears and the terminal becomes active.

## Two Modes

### Mode B — Returning launch

Shown when `config/settings.yaml` exists and contains all required credential fields (`api_key`, `client_id`, `password`, `totp_secret`).

```
┌─────────────────────────────────┐
│   Trading Terminal              │
│   Connect to your broker...     │
│                                 │
│   Welcome back, AB1234          │
│        Angel SmartAPI           │
│                                 │
│   [ Connect ]                   │
│   [ Cancel  ]                   │
│   Edit credentials              │
└─────────────────────────────────┘
```

Clicking **Edit credentials** switches to Mode A with all fields pre-filled.
Clicking **Cancel** closes the dialog — the terminal stays open in disconnected state.

### Mode A — First launch / form

Shown when `config/settings.yaml` is missing or incomplete.

```
┌─────────────────────────────────┐
│   Trading Terminal              │
│   Connect to your broker...     │
│                                 │
│   Broker     [ Angel SmartAPI ▼]│
│   API Key    [__________________]│
│   Client ID  [__________________]│
│   Password   [__________________]│
│   TOTP Secret[__________________]│
│                                 │
│   ☑ Save credentials to yaml    │
│                                 │
│   [ Cancel ]  [ Connect ]       │
└─────────────────────────────────┘
```

Clicking **Cancel** on first launch calls `QApplication.quit()` — exits the app.
If "Edit credentials" was used to get here from Mode B, Cancel returns to Mode B.

## Connect Worker Thread

`connect()` is **never** called on the Qt main thread. It runs in `_ConnectWorker(QThread)`:

```python
class _ConnectWorker(QThread):
    success = Signal()
    failure = Signal(str)

    def run(self):
        try:
            ok = BrokerManager.get_broker().connect()
            if ok:
                self.success.emit()
            else:
                self.failure.emit("Connection returned False")
        except BrokerAPIError as e:
            self.failure.emit(str(e))
```

While connecting, the Connect/Cancel buttons are disabled and the Connect label reads "Connecting…".

## On Success

1. If "Save credentials" checked: write full YAML to `config/settings.yaml`.
2. Emit `login_successful(client_id, broker_name)` signal.
3. `LoginWindow.accept()` — closes the dialog.
4. `MainWindow.on_login_success()`:
   - Hides the disconnected banner.
   - Enables the dock area.
   - Updates status bar: green dot, "Connected", broker name, client ID.
   - Enables **View → Add Widget** menu.

## On Failure

- Connect/Cancel buttons re-enabled.
- Error message shown inline in red below the card.
- Dialog stays open — user can fix credentials and retry.

## AppState Integration

```python
AppState.is_connected() -> bool
```

After login: `AppState.set_connected(True)` is called in `MainWindow.on_login_success()`.
Widgets check `AppState.is_connected()` to decide whether to start data subscriptions.

## Startup Sequence

```
main.py
  → QApplication created
  → MainWindow created + shown (disconnected state, banner visible)
  → MainWindow.show_login()
      → LoginWindow(modal)
          → Mode B or Mode A based on settings.yaml presence
          → User clicks Connect
          → _ConnectWorker.run() [background thread]
          → success → login_successful signal → MainWindow.on_login_success()
          → LoginWindow.accept()
  → show_login() returns True
  → app.exec() — Qt event loop starts
```

## Credential Storage

Written to `config/settings.yaml` (gitignored). Full structure:

```yaml
broker:
  name: angel
  api_key: "..."
  client_id: "..."
  password: "..."
  totp_secret: "..."
app:
  theme: dark
  log_level: INFO
```

Never written with partial data — always the complete structure or not at all.

## Broker-aware login (Angel + Zerodha Kite)

The login dialog has a **broker dropdown**. Credentials are stored in per-broker
sub-sections so both can be configured:

```yaml
broker:
  name: kite            # active broker
  angel: { api_key, client_id, password, totp_secret }
  kite:  { api_key, api_secret, redirect_port, access_token, access_token_date }
```

Legacy flat-Angel `settings.yaml` files are auto-migrated under `broker.angel`.

### Angel
TOTP form (api_key / client_id / password / totp_secret) → `broker.connect()`
authenticates directly.

### Zerodha Kite (OAuth redirect)
1. Form collects `api_key` + `api_secret` only.
2. On Connect, a worker thread runs `broker/kite_auth.py` →
   `capture_request_token()`: starts a localhost server on
   `http://127.0.0.1:5010/` and opens the system browser to Zerodha's login page.
   **This URL must match the redirect URL registered in the Kite developer app.**
3. After login, Zerodha redirects with a one-time `request_token`, captured by the
   local server; `KiteBroker.connect()` exchanges it (with `api_secret`) for the
   daily `access_token`.
4. The `access_token` is cached in `settings.yaml` with its date. On a same-day
   relaunch the cached token is validated silently (no browser). It expires at
   ~6 AM IST; an expired/rejected token falls back to the browser flow.
