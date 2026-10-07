# packages/data — market-data cache & fetchers

`bars.py`: daily OHLCV via Yahoo v8 chart API (no key). The only fetcher
so far; the planned SQLite/DuckDB cache with TTL lands here next, so
the morning sessions stop re-fetching the same six names.

Free-tier notes live in the docstring — short version: Yahoo v8 works,
Stooq is bot-walled, yfinance-the-package is throttled, Alpaca free is
IEX-only.

## Cache + intraday (2026-10-07)

`cache.py`: stdlib SQLite TTL cache (`~/.cache/muse-trading/bars.db`).
Every fetcher goes through `cached(key, ttl_s, fetch_fn)` — daily 15 min,
intraday 5 min. A full morning session now costs ~6 Yahoo requests
instead of ~60 (cold 1.0s → cached 0.001s).

`fetch_intraday(symbol, interval="5m", range_="5d")`: same v8 endpoint,
5m/15m bars for precise MAE/MFE and session RVOL. Daily highs/lows are
an approximation once a position is open — intraday is the fix.
