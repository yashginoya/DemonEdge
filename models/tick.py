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
    # open_interest: current OI in contracts (raw int64 from Angel One binary protocol)
    # open_interest_change: change from previous day's OI in contracts (raw int64;
    #   the SmartWebSocketV2 library names this field "open_interest_change_percentage"
    #   but it is stored as int64 — it represents the absolute contract count change,
    #   not a percentage)
    open_interest: int | None = None
    open_interest_change: int | None = None
