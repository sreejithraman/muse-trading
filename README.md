# muse-trading

Open-source monorepo of trading tools built by **Mu$e**, an AI trading
agent running a real swing-trading operation (Robinhood cash account —
US equities + Level 2 options, 5–8 concentrated positions, 1–6 week
holds, catalyst-driven, benchmarked vs QQQ).

Full rationale: `~/workspace/research/trading-tools-survey.md` (2026-10-06).

## Layout

- `packages/thesis` — **built.** Structured thesis tracker: one file per
  holding with claim, falsifiable KPIs, append-only evidence for/against,
  key dates, red lines (trigger → action), lifecycle verdicts
  (INTACT / WEAKENED / BROKEN), decision log. Borrowed schema pattern from
  investskill/yourich; nothing off-the-shelf fits an agent-run book.
- `packages/ta` — **built.** Pure-python signals (stdlib only): Wilder's ATR
  with dynamic-stop suggestions, RVOL unusual-volume flag, relative
  strength vs QQQ, volatility-regime flag. TA-Lib evaluated but skipped
  for v1 (zero install risk; ATR/RVOL/RS are ~60 lines). opengreeks is
  the planned engine for correct Greeks/IV on Level 2 options work.
- `packages/screen` — **built.** tvscreener (free TradingView scanner API)
  as universe filter + own scoring (momentum + RVOL + gap + catalyst
  proximity via upcoming-earnings flags). Human stays the final filter;
  edge is catalyst judgment.
- `packages/analytics` — **built.** Thin bespoke analytics on the
  machine-written record: open-position MAE/MFE, holding periods,
  QQQ-relative attribution; closed-trade win-rate framework (honest
  about n=0).
- `packages/options` — **built.** Single-leg fit-checker: Black-Scholes
  fair value, IV vs HV, Greeks, breakeven, and the book's guardrails
  (10% max, ≥30 DTE, -50% exit). Evaluates; never trades.
- `packages/charts` — TradingView lightweight-charts (Apache-2.0) via
  streamlit-lightweight-charts-pro; mplfinance for static PNGs in reports.
  Annotations: entries, stops, targets, thesis events.
- `packages/data` — **built (v1).** Daily OHLCV via Yahoo v8 chart API
  (no key); the planned SQLite/DuckDB cache with TTL lands here next.
  Robinhood MCP stays the execution-time source of truth.
- `apps/dashboard` — Streamlit: book vs QQQ, drawdown, stop distances,
  thesis status pills, annotated charts per holding.

## Explicitly out of scope

Backtesting event-driven catalyst trades (theater — can't backtest
"AZN invests $2B" with price bars), freqtrade-style bots (wrong game:
cash account, no leverage, T+1), paid data feeds (wrong account size),
human day-trader journals (our ledger is machine-written; adopting one
is a step backward).

## Data realities (free tier)

yfinance ~5 req/min conservative (429s since 2024 tightening) — fine for
6 holdings + small watchlist with caching, not for universe screening.
Yahoo v8 chart API (no key) works as the daily-bar fallback. Stooq's
free CSV is now behind a JS bot challenge (2026-10-06) — dead as a
server-side source. Alpaca free is IEX-only (~2–3% of volume),
200 req/min — fine for liquid names. Options flow is paywalled
industry-wide; free path is scanning chains for volume-vs-OI anomalies
ourselves.
