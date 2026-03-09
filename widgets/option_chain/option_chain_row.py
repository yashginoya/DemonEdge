"""Dataclass representing one strike row in the option chain."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OptionChainRow:
    strike: float

    # CE side
    ce_token: str = ""
    ce_ltp: float = 0.0
    ce_oi: int = 0
    ce_oi_change: int = 0
    ce_iv: float = 0.0
    ce_delta: float = 0.0
    ce_volume: int = 0

    # PE side
    pe_token: str = ""
    pe_ltp: float = 0.0
    pe_oi: int = 0
    pe_oi_change: int = 0
    pe_iv: float = 0.0
    pe_delta: float = 0.0
    pe_volume: int = 0

    # ATM flag
    is_atm: bool = False
