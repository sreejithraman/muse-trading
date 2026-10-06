# packages/screen — screener pipeline

tvscreener (free TradingView scanner API) filters the US market; we score
for *our* game. The screen surfaces ideas — it never decides.

## Universe

US-listed, market cap ≥ $2B, price ≥ $10, 30-day avg volume ≥ 500k shares.
OTC excluded on purpose: this book can't trade pink sheets at size.

## Scoring (`screen.py`)

Z-scored within the universe, composite:

```
score = 0.35 * z(1-week %)   # momentum persistence
      + 0.30 * z(rel volume)  # unusual activity
      + 0.15 * z(day %)       # fresh move
      + 0.10 * z(gap %)       # overnight repricing
      + 0.10 * z(1-month %)   # trend backdrop
```

Weights are documented, not tuned — this is a surfacing tool, not a
backtest. Plus a catalyst flag: earnings within 21 days get marked
(`~Nd`), because the edge here is catalyst judgment and the human
stays the final filter.

## Usage

```bash
~/workspace/trading-tools/.venv/bin/python test_drive.py
```

Needs `tvscreener` (`pip install tvscreener`) — the only non-stdlib
dependency in the monorepo so far.

## Notes

- tvscreener's API is enum-heavy and underdocumented; the working
  pattern (Market enum, FilterOperator.ABOVE_OR_EQUAL, client-side
  price/volume filters on display columns) is in `screen.py`.
- 2026-10-06 test: 247 names screened, top hit CEG (+16.6% 1W,
  RVOL 4.65, +8.8% gap) — a real move, correctly surfaced.
  None of the book's six holdings ranked top-30 (a momentum screen
  and a quiet book agree with each other).
