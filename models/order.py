from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Order:
    order_id: str = ""
    symbol: str = ""
    token: str = ""
    exchange: str = ""
    side: str = ""               # "BUY" or "SELL"
    order_type: str = ""         # "MARKET", "LIMIT", "STOPLOSS", "STOPLOSS_MARKET"
    product_type: str = ""       # "INTRADAY", "DELIVERY", "CARRYFORWARD"
    variety: str = ""            # "NORMAL", "STOPLOSS", "AMO", "ROBO", "COVER"
    quantity: int = 0
    price: float = 0.0
    trigger_price: float = 0.0   # for SL / SL-M orders
    # Bracket order fields
    squareoff: float = 0.0
    stoploss: float = 0.0
    trailing_stoploss: float = 0.0
    # Metadata
    status: str = ""
    status_message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    filled_quantity: int = 0
    average_price: float = 0.0
