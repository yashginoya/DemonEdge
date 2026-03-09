from dataclasses import dataclass


@dataclass
class Position:
    symbol: str = ""
    token: str = ""
    exchange: str = ""
    product_type: str = ""           # "INTRADAY", "DELIVERY", "CARRYFORWARD"
    quantity: int = 0                # net quantity (positive = long, negative = short)
    overnight_quantity: int = 0
    buy_quantity: int = 0
    sell_quantity: int = 0
    average_price: float = 0.0
    buy_average: float = 0.0
    sell_average: float = 0.0
    ltp: float = 0.0
    close_price: float = 0.0        # previous close, for overnight P&L
    # Computed live
    unrealized_pnl: float = 0.0     # (ltp - average_price) * quantity
    realized_pnl: float = 0.0       # from broker response
    total_pnl: float = 0.0          # unrealized_pnl + realized_pnl
