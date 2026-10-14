"""Volatility-aware position sizing.

Paper: DXRG 2609.05663 §5.1, §8.1 — the largest measured defect in the
record is volatility-blind sizing (median leverage flat at 5x across a 5.7x
volatility spread; median realized return degrading ~10x from the calmest to
the wildest sextile). Size is computed in code here, never a judgment call.

Formula:
  vol         = ATR(14) / price              (daily volatility unit)
  scalar      = clamp(TARGET_VOL / vol, 0.25, 1.5)
  regime      = QQQ vol regime (high -> 0.5, else 1.0)
  notional    = base_notional * scalar * regime
  risk cap    : notional * stop_pct <= MAX_RISK_PCT * equity

The morning session calls suggest() when sizing an entry; the scalar and
regime are logged so sizing stays auditable.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "data"))
sys.path.insert(0, str(_HERE.parent / "ta"))
import bars  # noqa: E402  (flat import: sibling packages use sibling imports)
import signals  # noqa: E402

TARGET_VOL = 0.025      # 2.5% daily — the volatility unit we size for
MIN_SCALAR = 0.25
MAX_SCALAR = 1.5
MAX_RISK_PCT = 0.02     # no single trade risks more than 2% of equity
HIGH_REGIME_CUT = 0.5   # halve size when QQQ vol regime is high


def _volatility(symbol: str) -> tuple[float | None, float | None]:
    """(ATR(14)/price, last close) for symbol, or (None, None)."""
    daily = bars.fetch_daily(symbol, range_="6mo")
    if len(daily) < 30:
        return None, None
    a = signals.atr(daily)
    px = daily[-1]["close"]
    if not a or not px:
        return None, None
    return a / px, px


def suggest(symbol: str, entry_price: float, equity: float,
            base_notional: float = 300.0,
            stop_pct: float | None = None) -> dict:
    """Volatility-scaled size suggestion. Never raises on data gaps."""
    vol, _ = _volatility(symbol)
    scalar = 1.0
    if vol and vol > 0:
        scalar = max(MIN_SCALAR, min(MAX_SCALAR, TARGET_VOL / vol))

    regime = "unknown"
    regime_scalar = 1.0
    try:
        qqq = bars.fetch_daily("QQQ", range_="6mo")
        r = signals.vol_regime(qqq)
        if r:
            regime = r
            if r == "high":
                regime_scalar = HIGH_REGIME_CUT
    except Exception:
        pass

    notional = base_notional * scalar * regime_scalar
    if stop_pct and stop_pct > 0:
        max_notional = MAX_RISK_PCT * equity / stop_pct
        notional = min(notional, max_notional)

    return {
        "symbol": symbol,
        "entry_price": round(entry_price, 2),
        "vol_pct": round(vol * 100, 2) if vol else None,
        "size_scalar": round(scalar, 2),
        "qqq_regime": regime,
        "regime_scalar": regime_scalar,
        "notional": round(notional, 2),
        "shares": round(notional / entry_price, 3) if entry_price else 0.0,
        "risk_pct": round(notional * (stop_pct or 0) / equity * 100, 2)
        if stop_pct and equity else None,
    }


def main() -> None:
    import json
    s = suggest("SOFI", 15.23, 1888.0, stop_pct=0.15)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
