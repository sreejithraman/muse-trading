# packages/data — market-data cache & fetchers

`bars.py`: daily OHLCV via Yahoo v8 chart API (no key). The only fetcher
so far; the planned SQLite/DuckDB cache with TTL lands here next, so
the morning sessions stop re-fetching the same six names.

Free-tier notes live in the docstring — short version: Yahoo v8 works,
Stooq is bot-walled, yfinance-the-package is throttled, Alpaca free is
IEX-only.
