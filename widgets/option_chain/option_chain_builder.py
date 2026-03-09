"""Builds option chain rows from the InstrumentMaster for a given underlying + expiry."""

from __future__ import annotations

from datetime import datetime

from broker.instrument_master import InstrumentMaster
from utils.logger import get_logger
from widgets.option_chain.option_chain_row import OptionChainRow

logger = get_logger(__name__)

_OPT_TYPES = {"OPTIDX", "OPTSTK"}


def build_chain(
    underlying_name: str,
    expiry: str,
    exchange: str = "NFO",
) -> list[OptionChainRow]:
    """Build a sorted list of OptionChainRow for the given underlying and expiry.

    Accesses InstrumentMaster._index directly for unfiltered full-scan performance.
    Strike prices are stored in paise in the master — divides by 100 for rupees.
    """
    rows_by_strike: dict[float, OptionChainRow] = {}

    for _, _, record in InstrumentMaster._index:
        if (
            record.get("name") != underlying_name
            or record.get("expiry") != expiry
            or record.get("exch_seg") != exchange
            or record.get("instrumenttype") not in _OPT_TYPES
        ):
            continue

        try:
            actual_strike = float(record.get("strike", "0")) / 100.0
        except (TypeError, ValueError):
            continue

        token = record.get("token", "")
        symbol = record.get("symbol", "")

        if actual_strike not in rows_by_strike:
            rows_by_strike[actual_strike] = OptionChainRow(strike=actual_strike)

        row = rows_by_strike[actual_strike]

        if symbol.endswith("CE"):
            row.ce_token = token
        elif symbol.endswith("PE"):
            row.pe_token = token

    result = sorted(rows_by_strike.values(), key=lambda r: r.strike)
    logger.debug(
        "OptionChainBuilder: %d strikes for %s %s %s",
        len(result),
        underlying_name,
        expiry,
        exchange,
    )
    return result


def get_expiries(underlying_name: str, exchange: str = "NFO") -> list[str]:
    """Return expiry strings for the given underlying, sorted nearest first."""
    expiry_set: set[str] = set()

    for _, _, record in InstrumentMaster._index:
        if (
            record.get("name") == underlying_name
            and record.get("exch_seg") == exchange
            and record.get("instrumenttype") in _OPT_TYPES
        ):
            exp = record.get("expiry", "")
            if exp:
                expiry_set.add(exp)

    def _parse(s: str) -> datetime:
        try:
            return datetime.strptime(s, "%d%b%Y")
        except ValueError:
            return datetime.max

    return sorted(expiry_set, key=_parse)


def get_atm_strike(rows: list[OptionChainRow], underlying_ltp: float) -> float:
    """Return the strike closest to underlying_ltp."""
    if not rows:
        return 0.0
    return min(rows, key=lambda r: abs(r.strike - underlying_ltp)).strike
