"""Black-Scholes implied volatility and Greeks calculator."""

from __future__ import annotations

import math


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes_price(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> float:
    """Black-Scholes option price.

    Parameters
    ----------
    S:            Underlying spot price.
    K:            Strike price.
    T:            Time to expiry in years.
    r:            Risk-free rate (e.g. 0.065 for 6.5%).
    sigma:        Volatility as a decimal (e.g. 0.20 for 20%).
    option_type:  "CE" or "PE".
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    from scipy.stats import norm

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == "CE":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def calculate_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    option_type: str,
    r: float = 0.065,
) -> float:
    """Calculate implied volatility using Newton-Raphson iteration.

    Returns IV as a percentage (e.g. 18.5 for 18.5%).
    Returns 0.0 if calculation fails or inputs are invalid.
    """
    if T <= 0 or market_price <= 0 or S <= 0 or K <= 0:
        return 0.0

    sigma = 0.3  # initial guess
    for _ in range(100):
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        vega = S * math.sqrt(T) * _norm_pdf(d1)
        if vega < 1e-10:
            break
        diff = price - market_price
        if abs(diff) < 1e-6:
            break
        sigma -= diff / vega
        if sigma <= 0:
            return 0.0

    return round(sigma * 100, 2) if 0 < sigma < 5 else 0.0


def calculate_delta(
    S: float,
    K: float,
    T: float,
    sigma: float,
    option_type: str,
    r: float = 0.065,
) -> float:
    """Returns delta (-1 to 1)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    from scipy.stats import norm

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1) if option_type == "CE" else norm.cdf(d1) - 1
