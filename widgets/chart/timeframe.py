from dataclasses import dataclass
from enum import Enum


@dataclass
class TimeframeInfo:
    label: str            # display label: "1m", "5m", "1h", "1D"
    angel_interval: str   # Angel API interval string
    seconds: int          # bar duration in seconds


class Timeframe(Enum):
    M1  = TimeframeInfo("1m",  "ONE_MINUTE",     60)
    M3  = TimeframeInfo("3m",  "THREE_MINUTE",   180)
    M5  = TimeframeInfo("5m",  "FIVE_MINUTE",    300)
    M15 = TimeframeInfo("15m", "FIFTEEN_MINUTE", 900)
    H1  = TimeframeInfo("1h",  "ONE_HOUR",       3600)
    D1  = TimeframeInfo("1D",  "ONE_DAY",        86400)
