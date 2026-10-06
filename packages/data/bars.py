"""Daily OHLCV bars via Yahoo Finance v8 chart API (no key).

Free-tier reality (2026-10-06): Stooq's CSV is behind a JS bot challenge;
yfinance the package is rate-limited aggressively; the raw v8 endpoint
with a browser UA works fine for a 6-name book + small watchlist.
Not for universe screening — that's tvscreener's job (packages/screen).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone


def fetch_daily(symbol: str, range_: str = "6mo") -> list[dict]:
    """Daily bars, oldest first. Keys: date, open, high, low, close, volume."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range={range_}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        try:
            o, h, l = q["open"][i], q["high"][i], q["low"][i]
            c = adj[i] if adj and adj[i] else q["close"][i]
            v = q["volume"][i] or 0
            if None in (o, h, l, c):
                continue
            bars.append({
                "date": datetime.fromtimestamp(t, timezone.utc).date().isoformat(),
                "open": o, "high": h, "low": l, "close": c, "volume": v})
        except (TypeError, IndexError):
            continue
    return bars


def last_close(symbol: str) -> float | None:
    bars = fetch_daily(symbol, range_="5d")
    return bars[-1]["close"] if bars else None
