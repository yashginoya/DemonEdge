"""Manual margin API test — NOT a pytest unit test.

Run with:
    uv run python tests/test_margin_manual.py

What it does:
  1. Loads credentials from config/settings.yaml via Config.
  2. Connects AngelBroker (TOTP auth).
  3. Calls get_order_margin() with HDFCBANK NSE equity params (BUY, 1 share, MARKET, INTRADAY).
  4. Prints the result or any error.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
logging.basicConfig(level=logging.DEBUG)

from utils.config import Config
from broker.angel_broker import AngelBroker

def main() -> None:
    broker_cfg = Config.get("broker", {})

    broker = AngelBroker(broker_cfg)
    print("Connecting to Angel SmartAPI…")
    ok = broker.connect()
    if not ok:
        print("Connection failed — check credentials in config/settings.yaml")
        sys.exit(1)
    print("Connected.\n")

    # HDFCBANK NSE token is 1333, LTP ~1800
    margin_params = {
        "exchange":    "NSE",
        "token":       "1333",
        "tradeType":   "BUY",
        "productType": "INTRADAY",
        "qty":         1,
        "price":       1800.0,   # approximate LTP (as sent for MARKET orders)
    }

    print(f"Requesting margin for: {margin_params}")
    # Patch to print raw API response before parsing
    original = broker._smart.getMarginApi
    def _patched(params):
        resp = original(params)
        print(f"\nRAW API response: {resp}")
        return resp
    broker._smart.getMarginApi = _patched

    try:
        margin = broker.get_order_margin(margin_params)
        print(f"\nOK Margin required: Rs {margin:,.2f}")
    except Exception as exc:
        print(f"\nERROR: {exc}")

if __name__ == "__main__":
    main()
