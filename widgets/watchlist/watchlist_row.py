from dataclasses import dataclass

from models.instrument import Instrument


@dataclass
class WatchlistRow:
    """Live state for a single row in the watchlist table."""

    instrument: Instrument
    ltp: float = 0.0
    prev_close: float = 0.0        # used to calculate change; set from initial REST fetch
    change: float = 0.0            # ltp - prev_close
    change_pct: float = 0.0        # (change / prev_close) * 100
    last_tick_direction: int = 0   # +1 uptick, -1 downtick, 0 unchanged
    flash_counter: int = 0         # counts down every 100ms; >0 means row is flashing
