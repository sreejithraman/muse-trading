"""Pure-python Black-Scholes: price, Greeks, IV.

Adequate for single-leg fit-checks (is the premium sane? what's the
breakeven? how fast does it decay?). We are not market-making — we
don't need microsecond calibration, we need correct-enough numbers
with zero install risk. opengreeks (Rust) remains the planned upgrade
if we ever need surface-accurate IV.

Conventions: theta reported per calendar day, vega per 1 vol point,
all rates annualized with ACT/365 day count.
"""
from __future__ import annotations

import math

SQRT_2PI = math.sqrt(2 * math.pi)


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _d1_d2(s: float, k: float, t: float, r: float, sigma: float):
    d1 = (math.log(s / k) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    return d1, d1 - sigma * math.sqrt(t)


def price(s: float, k: float, t: float, r: float, sigma: float,
          kind: str = "call") -> float:
    """Option price. t in years, sigma annualized. kind: call|put."""
    if t <= 0 or sigma <= 0:
        return max(0.0, (s - k) if kind == "call" else (k - s))
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    disc = math.exp(-r * t)
    if kind == "call":
        return s * _ncdf(d1) - k * disc * _ncdf(d2)
    return k * disc * _ncdf(-d2) - s * _ncdf(-d1)


def greeks(s: float, k: float, t: float, r: float, sigma: float,
           kind: str = "call") -> dict:
    """delta, gamma, theta/day, vega per vol point."""
    if t <= 0 or sigma <= 0:
        return {"delta": 1.0 if kind == "call" and s > k else 0.0,
                "gamma": 0.0, "theta_day": 0.0, "vega": 0.0}
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    disc = math.exp(-r * t)
    gamma = _npdf(d1) / (s * sigma * math.sqrt(t))
    vega = s * _npdf(d1) * math.sqrt(t) / 100.0
    if kind == "call":
        delta = _ncdf(d1)
        theta = (-(s * _npdf(d1) * sigma) / (2 * math.sqrt(t))
                 - r * k * disc * _ncdf(d2)) / 365.0
    else:
        delta = _ncdf(d1) - 1.0
        theta = (-(s * _npdf(d1) * sigma) / (2 * math.sqrt(t))
                 + r * k * disc * _ncdf(-d2)) / 365.0
    return {"delta": round(delta, 3), "gamma": round(gamma, 4),
            "theta_day": round(theta, 4), "vega": round(vega, 4)}


def implied_vol(mkt_price: float, s: float, k: float, t: float,
                r: float, kind: str = "call") -> float | None:
    """IV via bisection. None if the price is below intrinsic (bad quote)."""
    intrinsic = max(0.0, (s - k) if kind == "call" else (k - s))
    if mkt_price < intrinsic - 1e-9:
        return None
    lo, hi = 0.01, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if price(s, k, t, r, mid, kind) < mkt_price:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)
