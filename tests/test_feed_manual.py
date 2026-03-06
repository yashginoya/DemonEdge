"""Manual MarketFeed integration test — NOT a pytest unit test.

Run with:
    uv run python tests/test_feed_manual.py

What it does:
  1. Loads credentials from config/settings.yaml via Config.
  2. Connects AngelBroker (TOTP auth) and prints auth_token + feed_token.
  3. Subscribes to NSE:2885 (RELIANCE) and NSE:3045 (SBIN) in LTP mode.
     Subscriptions are queued before the WebSocket connects — this exercises
     the pending-queue path in MarketFeed.
  4. Starts the MarketFeed WebSocket (daemon thread).
  5. Prints every incoming tick for 30 seconds.
  6. Disconnects and exits.

Requirements:
  - config/settings.yaml must exist with valid Angel credentials.
  - The terminal must be run during market hours for live ticks.
    Outside hours the feed connects but no ticks arrive (expected).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure project root is on sys.path so package imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# QCoreApplication is required before any QObject (including MarketFeedSignals)
# can be instantiated.  We use QCoreApplication (no GUI) to keep this lightweight.
from PySide6.QtCore import QCoreApplication

_qt_app = QCoreApplication(sys.argv)

# --- project imports (after sys.path and QCoreApplication are set up) ---
from broker.angel_broker import AngelBroker
from feed.feed_models import SubscriptionMode
from feed.market_feed import MarketFeed
from utils.config import Config


# ---------------------------------------------------------------------------
# Tick callback — called on the feed daemon thread.
# print() is thread-safe (GIL-protected) so direct printing is fine here.
# ---------------------------------------------------------------------------

def on_tick(tick) -> None:
    print(
        f"TICK | {tick.token:>6} | LTP: {tick.ltp:>10.2f} "
        f"| Time: {tick.exchange_timestamp.strftime('%H:%M:%S.%f')[:-3]}"
    )


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Load credentials
    # ------------------------------------------------------------------
    try:
        credentials = {
            "api_key":      Config.get("broker.api_key"),
            "client_id":    Config.get("broker.client_id"),
            "password":     Config.get("broker.password"),
            "totp_secret":  Config.get("broker.totp_secret"),
        }
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    print(f"[INFO] Connecting as client_id={credentials['client_id']} …")

    # ------------------------------------------------------------------
    # 2. Connect broker — generates auth_token + feed_token via TOTP
    # ------------------------------------------------------------------
    broker = AngelBroker(credentials)
    try:
        ok = broker.connect()
    except Exception as exc:
        print(f"[ERROR] broker.connect() raised: {exc}")
        sys.exit(1)

    if not ok:
        print("[ERROR] broker.connect() returned False — check credentials.")
        sys.exit(1)

    print(f"[INFO] auth_token  : {broker.auth_token[:40]}…")
    print(f"[INFO] feed_token  : {broker.feed_token[:40]}…")
    print(f"[INFO] client_code : {broker.client_code}")
    print()

    # ------------------------------------------------------------------
    # 3. Subscribe BEFORE connect — exercises the pending-queue path.
    #    Pending items are flushed to the WebSocket in _on_open().
    # ------------------------------------------------------------------
    MarketFeed.instance().subscribe("NSE", "2885", on_tick, SubscriptionMode.LTP)
    MarketFeed.instance().subscribe("NSE", "3045", on_tick, SubscriptionMode.LTP)
    print("[INFO] Subscribed (pending): NSE:2885 (RELIANCE), NSE:3045 (SBIN)")

    # ------------------------------------------------------------------
    # 4. Start the WebSocket feed (non-blocking — runs on daemon thread)
    # ------------------------------------------------------------------
    MarketFeed.connect(broker)
    print("[INFO] MarketFeed.connect() called — waiting for WebSocket handshake …")
    print("[INFO] Listening for 30 seconds. Run during market hours for live ticks.")
    print("-" * 60)

    # ------------------------------------------------------------------
    # 5. Keep alive for 30 seconds
    # ------------------------------------------------------------------
    try:
        time.sleep(30)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")

    # ------------------------------------------------------------------
    # 6. Disconnect and exit
    # ------------------------------------------------------------------
    print("-" * 60)
    print("[INFO] Disconnecting …")
    MarketFeed.disconnect()
    print("[INFO] Done.")


if __name__ == "__main__":
    main()
