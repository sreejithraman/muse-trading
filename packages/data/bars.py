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

from cache import cached

DAILY_TTL = 900      # today's daily bar still moves
INTRADAY_TTL = 300   # 5m bars during the session


def _fetch(symbol: str, interval: str, range_: str) -> list[dict]:
    """Raw Yahoo v8 fetch. Keys: ts (epoch), open, high, low, close, volume."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval={interval}&range={range_}")
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
                "date": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                "open": o, "high": h, "low": l, "close": c, "volume": v})
        except (TypeError, IndexError):
            continue
    return bars


def fetch_daily(symbol: str, range_: str = "6mo") -> list[dict]:
    """Daily bars, oldest first (date-only timestamps). Cached 15 min."""
    bars = cached(f"bars:{symbol}:1d:{range_}", DAILY_TTL,
                  lambda: _fetch(symbol, "1d", range_))
    return [{**b, "date": b["date"][:10]} for b in bars]


def fetch_intraday(symbol: str, interval: str = "5m",
                   range_: str = "5d") -> list[dict]:
    """Intraday bars (full ISO timestamps), oldest first. Cached 5 min.

    Yahoo serves 1m for ~1d, 5m/15m for ~5d. Use for precise MAE/MFE,
    session RVOL, and same-day excursion — daily highs/lows are only
    an approximation once a position is open.
    """
    if interval not in ("1m", "5m", "15m", "30m", "1h"):
        raise ValueError(f"unsupported intraday interval: {interval}")
    return cached(f"bars:{symbol}:{interval}:{range_}", INTRADAY_TTL,
                  lambda: _fetch(symbol, interval, range_))


def last_close(symbol: str) -> float | None:
    bars = fetch_daily(symbol, range_="5d")
    return bars[-1]["close"] if bars else None
