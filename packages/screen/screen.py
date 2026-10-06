"""Screener pipeline: tvscreener universe filter + proprietary scoring.

tvscreener (free TradingView scanner API) does what it's good at —
filtering the whole US market by liquidity and size. We do what it's
bad at — scoring names for *our* game: multi-week swing holds where the
edge is catalyst judgment, not indicator soup.

Scoring (z-scored within the universe, transparent by design):
    score = 0.35 * z(perf_1w)      # momentum persistence
          + 0.30 * z(rvol)          # unusual activity
          + 0.15 * z(day_change)    # fresh move
          + 0.10 * z(gap_pct)       # overnight repricing
          + 0.10 * z(perf_1m)       # trend backdrop

Plus a catalyst flag: earnings within 21 days get marked — the human
(Sreejith) stays the final filter; the screen surfaces, it doesn't decide.

Universe defaults: US, market cap >= $2B, price >= $10, avg daily
volume >= 500k shares. Penny stocks and illiquid names are excluded
on purpose: this book can't trade them at size.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from tvscreener import StockScreener, StockField
from tvscreener.field import Market
from tvscreener.filter import FilterOperator as F

WEIGHTS = {
    "perf_1w": 0.35,
    "rvol": 0.30,
    "day_change": 0.15,
    "gap_pct": 0.10,
    "perf_1m": 0.10,
}

# TradingView display column names (stable across tvscreener versions)
COLS = {
    "ticker": "Symbol",
    "name": "Name",
    "price": "Price",
    "mcap": "Market Capitalization",
    "volume": "Volume",
    "perf_1w": "Change 1W, %",
    "perf_1m": "Change 1M, %",
    "day_change": "Change %",
    "gap_pct": "Gap %",
    "rvol": "Relative Volume",
    "earnings": "Upcoming Earnings Date",
}


def fetch_universe(min_mcap: float = 2_000_000_000,
                   min_price: float = 10.0,
                   min_avg_vol: float = 500_000,
                   limit: int = 400) -> pd.DataFrame:
    """Pull the liquid-US-stock universe from TradingView's scanner."""
    s = StockScreener()
    s.set_markets(Market.AMERICA)
    s.add_filter(StockField.MARKET_CAPITALIZATION, F.ABOVE_OR_EQUAL, min_mcap)
    s.set_range(0, limit)
    df = s.get()
    keep = [c for c in COLS.values() if c in df.columns]
    out = df[keep].copy()
    # price / liquidity filters client-side (stable display columns)
    out = out[pd.to_numeric(out[COLS["price"]], errors="coerce") >= min_price]
    vol_col = "Average Volume (30 day)"
    if vol_col in out.columns:
        out = out[pd.to_numeric(out[vol_col], errors="coerce") >= min_avg_vol]
    # no OTC: this book can't trade pink sheets at size
    out = out[~out[COLS["ticker"]].astype(str).str.startswith("OTC:")]
    return out.reset_index(drop=True)


def _z(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    std = s.std()
    return (s - s.mean()) / std if std and std > 0 else s * 0


def score(df: pd.DataFrame) -> pd.DataFrame:
    """Add z-scored components and the composite score, ranked desc."""
    out = df.copy()
    for key, w in WEIGHTS.items():
        col = COLS[key]
        out[f"z_{key}"] = _z(out[col]) * w
    out["score"] = sum(out[f"z_{k}"] for k in WEIGHTS)
    out["catalyst_flag"] = out[COLS["earnings"]].apply(_earnings_flag)
    return out.sort_values("score", ascending=False).reset_index(drop=True)


def _earnings_flag(val) -> str:
    """'~Xd' if earnings within 21 days, else ''."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        d = (datetime.fromtimestamp(val).date() if isinstance(val, (int, float))
             else datetime.strptime(str(val)[:10], "%Y-%m-%d").date())
        delta = (d - date.today()).days
        return f"~{delta}d" if 0 <= delta <= 21 else ""
    except (ValueError, TypeError, OSError):
        return ""
