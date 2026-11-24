# Pending theses — pre-registered entry triggers

A pending thesis is a judged idea *waiting for its entry condition*, not a
position. The morning session (or the user) rules an idea in, writes the
pending thesis with the entry already decided — trigger, max price, red line,
size — and arms it. When the trigger fires during market hours, the entry
executes without a 9:40 session deliberation (rule 2026-11-24, Sreejith:
"let a pre-registered trigger fire the entry"). The judgment moves *before*
the event instead of after it — that is the whole point (NVDA: the
reinstatement resolved at 9:07 AM and gapped +31% before the session could
deliberate).

## Lifecycle

`draft` → `armed` → `fired` | `expired` | `cancelled`

- `draft`: written, not live. The session judges it (arm, amend, or cut).
  Drafts never emit to the watchlist and can never fire.
- `armed`: live. Emitted to `~/hooks/state/watchlist.json` by
  `checkin.py --emit-watchlist`; the 15-min circuit-watch evaluates it.
- `fired`: the entry executed; the pending file is the audit trail. The
  live thesis now lives in `../theses/<TICKER>.yaml` with `record_fill()`
  provenance.
- `expired`: the trigger did not fire by `expires`. It dies — no silent
  extension. Re-arming is a new session decision with new levels.
- `cancelled`: Sreejith or a session killed it. He can cancel any pending
  trigger at any time.

## Schema (one YAML per idea, `<TICKER>.yaml`)

```yaml
ticker: MRVL
name: Marvell Technology
status: draft            # draft | armed | fired | expired | cancelled
source: spiky-scan 2026-11-24   # idea inbox | spiky scan | user flag
created: '2026-11-24'
expires: '2026-12-01'    # trigger dies after this date
claim: ...               # one-line thesis sketch
fear: ...                # what the market is pricing
catalyst:                # dated reason or live process (rule 2026-11-24)
  kind: earnings         # earnings | live_process | fda | ...
  event: Q3 FY27 earnings
  date: '2026-12-01'
  resolution: ...        # what counts as resolution
entry:
  condition: stabilization   # v1: the only trigger condition
  reference_close: 122.28    # washout-day close (the level to reclaim)
  washout_low: 120.56        # washout-day intraday low (the level not to retest)
  max_price: 150.00          # HARD CAP — never chase above it, ever
  red_line: 120.00           # close below -> exit next session
  instrument: shares         # v1: shares only; option expressions stay session-decided
  base_notional: 300.0       # sizing input for packages/sizing/size.py
confirmation: ...            # pre-registered observable that the thesis was RIGHT
decisions: []                # append-only: armed / amended / fired / expired / cancelled
```

## STABILIZATION (v1) — the trigger condition

Evaluated by the circuit-watch at a 15-min poll at or after 10:00 AM ET.
ALL four must hold:

1. **Not a gap day** — today's open within ±3% of the prior close. The
   trigger buys fear before resolution, never a relief/event gap. (Monday
   Nov 23 was a +18% gap day for MRVL — correctly a no-fire.)
2. **No retest** — today's intraday low so far is above the washout low.
   The name has held above its washout low all session.
3. **Reclaimed** — current price ≥ reference close (the washout-day close).
4. **Hard cap** — current price ≤ max price. The cap is the anti-chase
   guard; a print above it never fires, however strong the tape.

Fires once per symbol per day (deduped in hook state). On fire, the hook
worker re-verifies the price via Robinhood MCP, runs the ATR sizer, and
executes: market entry within the max price, native stop + mechanical
take-profit (half at 2× stop distance) at open, thesis promotion with
`record_fill()` provenance, watchlist re-emit, report in the usual
what/why/exposure shape.

## What this is not

- Not a new screen: names arrive from the idea inbox, the spiky scan, or
  the user. This registry only holds judged ideas waiting for a trigger.
- Not option triggers: v1 fires equity entries only. An option expression
  (defined-risk call) is priced by the session at entry time.
- Not a standing order: no broker order exists until the trigger fires.
  Cancelling is deleting a file line, not cancelling an order.

## Private data

Pending theses carry trading intent (max prices, red lines) — they stay
local, never pushed (`.gitignore`: `packages/thesis/pending/*.yaml`).
