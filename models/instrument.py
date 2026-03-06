from dataclasses import dataclass, field


@dataclass
class Instrument:
    symbol: str
    token: str
    exchange: str
    name: str
    instrument_type: str
    # Optional fields — populated when loaded from instrument master
    expiry: str = ""
    strike: float = -1.0
    lot_size: int = 1
    tick_size: float = 0.05
