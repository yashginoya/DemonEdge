from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    exchange: str
    quantity: int
    average_price: float
    ltp: float
    pnl: float
