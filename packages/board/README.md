# Board — Mu$e's Book data + templates

The deterministic split behind **Mu$e's Book** (the trading tracker space),
built from Sreejith's 2026-11-10 direction: stop re-prompting the page
builder for every fix; instead, code emits the data and a versioned template
decides the layout, so page length is deterministic and a label/color can
never drift as a side effect of an unrelated change.

## The split

| Piece | File | Public-safe? |
|---|---|---|
| Section templates (order, caps, display rules) | `templates.json` | **Yes** — no tickers, prices, or levels |
| Board data (positions, scorecard, exits, paper) | `board.private.json` | **No** — live stop levels live here |
| Generator (thesis YAMLs -> board data) | `generate.py` | **Yes** — reads the private YAMLs, emits private JSON |

## Public / private rule

`board.private.json` must never reach the public muse-trading repo. The
sync script (`~/workspace/bin/sync-muse-trading.sh`) excludes
`*.private.json` from the rsync and the grep gate refuses the push if any
private filename slips through. `templates.json` and `generate.py` sync
normally. The dev workbench space (Mu$e's Book Dev) seeds fixtures only —
never paste live board data into it.

## Generating

```bash
python3 packages/board/generate.py \
  --prices '{"ACME": 10.00, "HELX": 25.00, "OPT": 16.00, "OPT_PREMIUM": 5.00}' \
  --account '{"total": 1000.00, "cash": 500, "qqq_gap_pp": 5.00}' \
  --as-of 2026-11-10
```

Prices are inputs, not stored in the repo: the morning/close sessions (or the
daily refresh cron) pass the live quotes they already fetched. The generator
reads only the thesis YAMLs, `packages/analytics/trades.yaml` (unused — the
exit log comes from CLOSED theses' FILL decisions, which is where the fills
actually live), and `packages/paper/ledger.yaml`.

Output defaults to `packages/board/board.private.json`.

## Deterministic length

`templates.json` fixes section order and caps (positions 6, exit log 7,
paper 6, watch 5, race 90 points). Data can grow; once a section hits its
cap the page stops growing. Layout changes ship as template commits —
reviewable, revertible — never as fresh builder judgment.

## Display rules settled 2026-11-10 (chat)

- Labels are price-first and read as decisions: "Bought $10.00",
  "Sell at $7.60", "Sell half $12.00", "Break even $12.50".
- Distance captions ("24% below now") sit attached to the tick they belong
  to, in one neutral color on every card. No arrows (a down arrow in green
  reads as a contradiction). Paused exits show via pill + tick label +
  card border — never via caption color.
- Options get **two gauges**: the stock gauge (price vs breakeven, plus the
  stock re-eval line) and a contract gauge (premium now vs the -50%
  premium exit vs the premium-double take-profit). The contract gauge
  carries the option's real sell line — an option card with no stock-price
  sell line still shows its exit here.
- "At risk" sorts by distance to the **primary** exit, closest first:
  equity -> stop; option -> premium exit. That puts the closest-to-its-exit
  position first.
- The race chart carries real axis labels and a "how to read this" note;
  the scorecard states the gap in a sentence and in "$100 invested" terms.
- Comparison is three-way — Mu$e (the account), QQQ (the benchmark), SPY
  (S&P 500 context, via SPY). QQQ stays the benchmark: gap, band color, and
  headline are vs QQQ only. The generator passes SPY through as
  `scorecard.spy_gap_pp` (from `--account`) and as a third series in
  `--series` points when the series is wired.
- Colors have one job each: identity — Mu$e green, QQQ gray, SPY steel-blue,
  only on chart lines, legend swatches, and the dot beside a series label;
  direction — bars and change values green up / red down; risk — red exit /
  danger tick, amber paused, green safe zone on gauges; neutral captions gray.
- Money always renders with exactly two decimals ($15.50, $2,000.00) — never
  one decimal, never three. Shorthand like $30M / $2B is left as-is.
- The account series is labeled "Mu$e", never "Us".

## Open wiring (not yet done)

- `race.series`: no persisted daily account-vs-QQQ series exists yet; the
  generator emits `"status": "not_wired"` until the session scoring writes
  one (pass `--series series.json` when it exists).
- `today.day_change`: intraday; fill from the close review, not the morning
  session. Left null in the sample.
- `watch`: the idea inbox has no machine-readable file yet; empty until
  one exists. Do not hand-write watch items into board data.
- Exit log holds 4 of the 5 mechanical exits: INTC's Oct 12 fill was
  logged as session prose, not via `record_fill()`, so the FILL parser
  misses it. Fix by backfilling a FILL decision in INTC.yaml, not by
  hand-editing board output.
