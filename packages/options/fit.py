"""Options fit-checker: is this single-leg idea worth the premium?

Given a proposed long call/put (ticker, strike, expiry, premium), it:
  - prices the contract on Black-Scholes at historical vol -> fair value
  - backs out implied vol from the quoted premium -> IV vs HV (are we
    buying inflated vol into an event?)
  - reports Greeks, breakeven, max loss, theta burn per day
  - runs the book's guardrails: premium <= 10% of account at cost,
    >= 30 DTE unless deliberately event-driven, exit at -50% reminder

Level 2 only: long calls/puts. No spreads, no naked anything.
This tool evaluates; it never trades.
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data"))

from bars import fetch_daily  # noqa: E402
from bs import greeks, implied_vol, price  # noqa: E402

RISK_FREE = 0.04  # annualized; param, not gospel


def hist_vol(bars: list[dict], window: int = 60) -> float | None:
    closes = [b["close"] for b in bars[-(window + 1):]]
    if len(closes) < window:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(252), 4)


def fit_check(ticker: str, kind: str, strike: float, expiry: str,
              premium: float, account_value: float,
              event_driven: bool = False) -> dict:
    """Full fit-check. expiry: YYYY-MM-DD. premium: quoted ask per share."""
    bars = fetch_daily(ticker, range_="6mo")
    s = bars[-1]["close"]
    dte = (date.fromisoformat(expiry) - date.today()).days
    t = max(dte, 1) / 365.0
    hv = hist_vol(bars)
    iv = implied_vol(premium, s, strike, t, RISK_FREE, kind)
    fair = price(s, strike, t, RISK_FREE, hv, kind) if hv else None
    g = greeks(s, strike, t, RISK_FREE, iv or hv or 0.5, kind)

    breakeven = strike + premium if kind == "call" else strike - premium
    cost = premium * 100
    cost_pct = cost / account_value * 100 if account_value else None
    flags = []
    if dte < 30 and not event_driven:
        flags.append(f"✖ {dte} DTE < 30-day minimum (not flagged event-driven)")
    if iv and hv and iv > hv * 1.5:
        flags.append(f"⚠ IV {iv:.0%} is >1.5x HV {hv:.0%} — vol is bid up")
    if fair and premium > fair * 1.25:
        flags.append(f"⚠ premium {premium:.2f} > 25% over HV fair value {fair:.2f}")

    return {
        "underlying": ticker, "underlying_px": round(s, 2),
        "kind": kind, "strike": strike, "expiry": expiry, "dte": dte,
        "quoted_premium": premium, "contract_cost": round(cost, 2),
        "hist_vol": hv, "implied_vol": iv,
        "fair_value_at_hv": round(fair, 2) if fair else None,
        "breakeven": round(breakeven, 2),
        "breakeven_pct": round((breakeven / s - 1) * 100, 1),
        "max_loss": round(cost, 2),
        "cost_pct_of_account": round(cost_pct, 1) if cost_pct is not None else None,
        "greeks": g,
        "theta_pct_per_day": round(-g["theta_day"] / premium * 100, 2) if premium else None,
        "flags": flags,
        "exit_rule": "exit at -50% premium or on thesis break",
    }


def report(fc: dict) -> str:
    L = []
    L.append(f"{fc['underlying']} {fc['kind']} ${fc['strike']:g} "
             f"exp {fc['expiry']} ({fc['dte']} DTE) @ ${fc['quoted_premium']:.2f}")
    L.append(f"  underlying ${fc['underlying_px']:.2f} | HV {fc['hist_vol']:.0%} "
             f"| IV {fc['implied_vol']:.0%} | fair@{fc['hist_vol']:.0%} "
             f"${fc['fair_value_at_hv']:.2f}")
    L.append(f"  breakeven ${fc['breakeven']:.2f} ({fc['breakeven_pct']:+.1f}%) | "
             f"max loss ${fc['max_loss']:.0f} | cost ${fc['contract_cost']:.0f} "
             f"({fc['cost_pct_of_account']}% of account)")
    g = fc["greeks"]
    L.append(f"  delta {g['delta']} | gamma {g['gamma']} | "
             f"theta {g['theta_day']}/day ({fc['theta_pct_per_day']}%/day of premium) | "
             f"vega {g['vega']}")
    for f in fc["flags"]:
        L.append(f"  {f}")
    L.append(f"  exit rule: {fc['exit_rule']}")
    return "\n".join(L)
