"""TA toolkit — pure-python technical signals for swing trading.

Dependency-free (stdlib only). All functions take OHLCV bars as a list of
dicts with keys: date, open, high, low, close, volume (oldest first) —
and return plain numbers. Data fetching lives in packages/data;
this module never touches the network.

Signals:
  atr()            Wilder's ATR(14) — the volatility unit for dynamic stops
  atr_stop()       suggested long stop: close - k*ATR (k=3 default for swing)
  rvol()           relative volume vs N-day average — unusual-activity flag
  rs_vs_benchmark() relative strength vs a benchmark (e.g. QQQ) over N days
  vol_regime()     ATR-as-%-of-price percentile vs history: low/normal/high
"""
from __future__ import annotations

import statistics


def _closes(bars: list[dict]) -> list[float]:
    return [float(b["close"]) for b in bars]


def true_ranges(bars: list[dict]) -> list[float]:
    """Wilder's true range per bar (first bar: high - low)."""
    trs = []
    prev_close = None
    for b in bars:
        h, l, c = float(b["high"]), float(b["low"]), float(b["close"])
        if prev_close is None:
            trs.append(h - l)
        else:
            trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
        prev_close = c
    return trs


def atr(bars: list[dict], period: int = 14) -> float | None:
    """Wilder's ATR. Needs at least period+1 bars; None if insufficient."""
    if len(bars) < period + 1:
        return None
    trs = true_ranges(bars)
    # seed with SMA of first `period` TRs, then Wilder's smoothing
    a = statistics.fmean(trs[:period])
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def atr_stop(bars: list[dict], k: float = 3.0, period: int = 14) -> dict | None:
    """Suggested long stop from volatility: close - k*ATR.

    Returns dict(close, atr, atr_pct, stop, stop_pct_from_close).
    k=3 suits multi-week swing holds; k=2 for tighter event trades.
    """
    a = atr(bars, period)
    if a is None:
        return None
    close = float(bars[-1]["close"])
    stop = close - k * a
    return {
        "close": round(close, 2),
        "atr": round(a, 2),
        "atr_pct": round(a / close * 100, 2),
        "k": k,
        "stop": round(stop, 2),
        "stop_pct_from_close": round((stop / close - 1) * 100, 2),
    }


def rvol(bars: list[dict], period: int = 20) -> float | None:
    """Relative volume: latest volume / SMA(volume, period)."""
    vols = [float(b.get("volume") or 0) for b in bars]
    if len(vols) < period + 1 or vols[-1] <= 0:
        return None
    base = statistics.fmean(v for v in vols[-(period + 1):-1] if v > 0)
    return round(vols[-1] / base, 2) if base > 0 else None


def rs_vs_benchmark(bars: list[dict], bench_bars: list[dict],
                    period: int = 20) -> float | None:
    """Relative strength vs benchmark over `period` days, in percent.

    +5.0 means the name outperformed the benchmark by 5pp over the window.
    """
    c, b = _closes(bars), _closes(bench_bars)
    if len(c) < period + 1 or len(b) < period + 1:
        return None
    r = (c[-1] / c[-(period + 1)]) / (b[-1] / b[-(period + 1)]) - 1
    return round(r * 100, 2)


def vol_regime(bars: list[dict], period: int = 14,
               lookback: int = 60) -> str | None:
    """Volatility regime from ATR-as-%-of-price percentile over `lookback` days."""
    if len(bars) < lookback + period:
        return None
    pcts = []
    for i in range(len(bars) - lookback, len(bars)):
        window = bars[max(0, i - period - 1):i + 1]
        a = atr(window, period)
        if a:
            pcts.append(a / float(window[-1]["close"]))
    if len(pcts) < 10:
        return None
    cur = pcts[-1]
    rank = sum(1 for p in pcts if p <= cur) / len(pcts)
    if rank >= 0.8:
        return "high"
    if rank <= 0.2:
        return "low"
    return "normal"
