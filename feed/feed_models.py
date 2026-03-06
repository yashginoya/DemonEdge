from enum import IntEnum


class SubscriptionMode(IntEnum):
    LTP = 1
    QUOTE = 2
    SNAP_QUOTE = 3
    DEPTH = 4


class ExchangeType(IntEnum):
    NSE_CM = 1   # NSE Cash / Equity
    NSE_FO = 2   # NSE F&O
    BSE_CM = 3   # BSE Cash / Equity
    BSE_FO = 4   # BSE F&O
    MCX_FO = 5   # MCX Commodity F&O


_EXCHANGE_STR_TO_TYPE: dict[str, ExchangeType] = {
    "NSE": ExchangeType.NSE_CM,
    "NFO": ExchangeType.NSE_FO,
    "BSE": ExchangeType.BSE_CM,
    "BFO": ExchangeType.BSE_FO,
    "MCX": ExchangeType.MCX_FO,
}

_EXCHANGE_TYPE_TO_STR: dict[int, str] = {v.value: k for k, v in _EXCHANGE_STR_TO_TYPE.items()}


def exchange_str_to_type(exchange: str) -> ExchangeType:
    """Convert an exchange string (e.g. 'NSE') to its ExchangeType int.

    Raises ValueError for unknown exchange strings.
    """
    try:
        return _EXCHANGE_STR_TO_TYPE[exchange.upper()]
    except KeyError:
        raise ValueError(
            f"Unknown exchange: {exchange!r}. Expected one of {list(_EXCHANGE_STR_TO_TYPE)}"
        )


def exchange_type_to_str(exchange_type: int) -> str:
    """Convert an ExchangeType int back to an exchange string (e.g. 1 → 'NSE').

    Returns the int as a string if not found.
    """
    return _EXCHANGE_TYPE_TO_STR.get(exchange_type, str(exchange_type))
