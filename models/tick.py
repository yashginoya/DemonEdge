from dataclasses import dataclass
from datetime import datetime


@dataclass
class Tick:
    """Parsed tick from SmartWebSocketV2.

    All price fields are in rupees (SmartAPI returns paise; converted on parse).
    Fields beyond ltp are None when subscription_mode is LTP (1).
    """

    token: str
    exchange_type: int          # ExchangeType int (1=NSE_CM, 2=NSE_FO, 3=BSE_CM, 4=BSE_FO, 5=MCX_FO)
    subscription_mode: int      # SubscriptionMode int (1=LTP, 2=QUOTE, 3=SNAP_QUOTE)
    sequence_number: int
    exchange_timestamp: datetime

    ltp: float                  # Last traded price in rupees

    # QUOTE / SNAP_QUOTE fields — None in LTP mode
    last_traded_quantity: int | None = None
    average_traded_price: float | None = None
    volume: int | None = None
    total_buy_quantity: float | None = None
    total_sell_quantity: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    # SNAP_QUOTE-only fields — None in LTP / QUOTE mode
    # open_interest: current OI as reported by Angel One binary protocol (raw int64).
    # The companion "open_interest_change_percentage" field from the binary packet
    # does not contain a usable absolute OI change value and is intentionally omitted.
    # OI change is computed per-widget as a delta from the first tick seen after load.
    open_interest: int | None = None
