# packages/analytics — ledger analytics

Thin, honest math on the machine-written record. No backtests, no
fabricated samples.

## What it computes (`analytics.py`)

**Open positions** (the useful half today): per thesis — days held,
return %, MAE/MFE (worst intraday dip / best intraday run vs blended
cost, from Yahoo daily bars since entry), QQQ return over the same
hold, and excess return in pp. Sorted by excess return, so the
laggards sit at the top where they belong.

**Closed trades**: win rate (overall + by setup tag), avg win/loss,
from `trades.yaml`. With no closed strategy trades it says so
plainly instead of inventing a track record.

## The day-1 batch

2026-09-18's 16 inherited-position exits (-$12.80 realized, AVAT +$6.14
the only winner, $240.63 gross proceeds — verified against the
brokerage order history) live in `trades.yaml` as ONE aggregate row.
Per-trade cost basis for inherited positions is unavailable, so it's
excluded from win-rate math. A cleanup, not a strategy signal.

## Usage

```bash
python3 test_drive.py
```

## Rules

- Nothing is estimated; small samples are labeled, not smoothed.
- Closed trades get appended to `trades.yaml` with a setup tag when
  they close — the framework is ready, the data accumulates.
- MAE/MFE on a blended-cost position that was added to is an
  approximation (single entry date). Directionally right, not
  accounting-grade.
