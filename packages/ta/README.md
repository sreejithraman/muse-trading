# packages/ta — TA toolkit

Pure-python technical signals for swing trading. Stdlib only, no installs.
All functions take OHLCV bars (oldest first) and return plain numbers —
data fetching lives in `packages/data`; this module never touches the
network (except `test_drive.py`, the demo).

## Signals (`signals.py`)

- `atr(bars, period=14)` — Wilder's ATR, the volatility unit
- `atr_stop(bars, k=3.0)` — suggested long stop: `close - k*ATR`.
  k=3 suits multi-week swing holds; k=2 for tighter event trades.
  **This is the dynamic-stop upgrade**: a biotech into an FDA binary
  and Intel should never share a stop methodology.
- `rvol(bars, period=20)` — relative volume vs 20-day average;
  the unusual-activity flag for the morning sessions
- `rs_vs_benchmark(bars, bench, period=20)` — relative strength vs QQQ
  in percent over the window
- `vol_regime(bars)` — ATR-as-%-of-price percentile vs 60d history:
  low / normal / high

## Demo

```bash
python3 test_drive.py   # live holdings vs QQQ, Yahoo daily bars
```

Sample output (2026-10-06) showed fixed -15%-style stops landing close
to ATR-implied levels on some names and far off on others — evidence for
moving the book to ATR-based stops per name. The demo ships with
illustrative fixed stops; drop a `fixed_stops.local.json` next to
`test_drive.py` (gitignored, never pushed) to compare your own book's
levels.

## Notes

- TA-Lib was evaluated (resurrected, healthy) but pure-python wins for
  v1: zero install risk on the VM, and ATR/RVOL/RS are ~60 lines.
  Revisit if we need the exotic indicators.
- pandas-ta / finta / backtrader: skipped (dead or theater).
- opengreeks (Rust, correct Greeks/IV) is the planned engine for the
  options fit-checker — separate package when needed.
