#!/usr/bin/env python3
"""Test-drive signals.py on live holdings with free Stooq daily bars.

Prints per ticker: price, ATR(14), ATR%, 3xATR suggested stop vs the
book's current fixed stop, RVOL(20), RS vs QQQ (20d), vol regime.
Read-only demo — touches no brokerage account.
"""
import csv
import io
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from signals import atr_stop, rvol, rs_vs_benchmark, vol_regime  # noqa: E402

TICKERS = ["MU", "INTC", "CRWD", "SMMT", "ARWR", "RKLB"]
# book's current fixed stops (exception: ARWR uses the $60 close rule)
FIXED_STOPS = {"MU": 872.92, "INTC": 103.80, "CRWD": 197.81,
               "SMMT": 14.46, "ARWR": 60.00, "RKLB": 59.79}


def fetch_bars(symbol: str) -> list[dict]:
    """Daily OHLCV bars via Yahoo Finance v8 chart API (no key)."""
    import json
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range=6mo")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    from datetime import datetime, timezone
    for i, t in enumerate(ts):
        try:
            o, h, l = q["open"][i], q["high"][i], q["low"][i]
            c = (adj[i] if adj and adj[i] else q["close"][i])
            v = q["volume"][i] or 0
            if None in (o, h, l, c):
                continue
            bars.append({
                "date": datetime.fromtimestamp(t, timezone.utc).date().isoformat(),
                "open": o, "high": h, "low": l, "close": c, "volume": v})
        except (TypeError, IndexError):
            continue
    return bars


def main() -> int:
    data = {t: fetch_bars(t) for t in TICKERS}
    qqq = fetch_bars("QQQ")
    missing = [t for t in TICKERS if len(data[t]) < 40]
    if missing or len(qqq) < 40:
        print(f"insufficient data for: {missing}", file=sys.stderr)
        return 1

    print(f"{'TKR':<5}{'PX':>9}{'ATR':>8}{'ATR%':>7}"
          f"{'3xATR-STOP':>11}{'FIXED':>9}{'RVOL':>6}{'RSvQQQ':>8}  REGIME")
    print("-" * 78)
    for t in TICKERS:
        bars = data[t]
        s = atr_stop(bars, k=3.0)
        rv = rvol(bars)
        rs = rs_vs_benchmark(bars, qqq)
        regime = vol_regime(bars)
        fixed = FIXED_STOPS[t]
        print(f"{t:<5}{s['close']:>9.2f}{s['atr']:>8.2f}{s['atr_pct']:>6.1f}%"
              f"{s['stop']:>11.2f}{fixed:>9.2f}{rv or 0:>6.2f}{rs or 0:>+7.1f}%  "
              f"{regime}")
    print("-" * 78)
    print("3xATR-STOP = volatility-based suggestion (close - 3*ATR14); "
          "FIXED = book's current stop. ARWR fixed is the $60 exception rule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
