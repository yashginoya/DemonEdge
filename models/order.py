from dataclasses import dataclass
from datetime import datetime


@dataclass
class Order:
    order_id: str
    symbol: str
    exchange: str
    side: str
    order_type: str
    quantity: int
    price: float
    status: str
    timestamp: datetime
