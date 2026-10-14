# Rule change log

The operation's rules are hypotheses, not fixtures. When a rule changes,
record it here: date, what changed, why, and how we'll know whether the new
one earned its place. A rule that changed without a written reason is just a
mood — the QQQ ledger judges whether the change worked, over subsequent
weeks of session scoring and attribution, not over one trade.

Newest entries go at the top.

---

## 2026-10-12 (evening) — Weekly catalyst sweep built (Oct 7 cadence promise completed)

- **What:** New `discovery-catalyst-sweep` cron, Sundays ~6:52 PM ET: week-ahead catalyst calendar — holdings' key_dates (verified within 14 days, YAML corrected if wrong), market-wide events (earnings, FDA/PDUFA, macro), and a collision check flagging mechanical lines within 10% with a binary inside 21 days. Writes to hidden_files; briefs chat with the top 3–5 events.
- **Why:** The Oct 7 idea cadence promised a weekly catalyst sweep; the audit found it (plus bi-weekly short interest, quarterly 13Fs) was never built — rule without machinery. Event dates were being hand-tracked (ARWR webinar, SMMT PDUFA, GRAB earnings).
- **Judged by:** whether Monday sessions start using it and collisions get caught before they matter.

## 2026-10-12 (evening) — SMMT $14.46 pre-committed through PDUFA (rules audit)

- **What:** SMMT's $14.46 mechanical close-stop suspended through Fri 11/13 — the final close before the Sat 11/14 FDA PDUFA on ivonescimab. Found in the audit Sreejith asked for after the ARWR rewrite: a binary name where a mechanical line and a binary event would otherwise collide. The PDUFA outcome is already SMMT's thesis-break red line, so it becomes the trigger; suspension lapses automatically.
- **Why:** Same principle as ARWR, applied in advance while calm instead of discovered on 11/13. Thesis-break exits never pause.
- **Judged by:** whether the PDUFA-week handling is clean; QQQ ledger.

## 2026-10-12 — ARWR $60 rule rewritten (judgment pause through webinar); near-tripwire checklist adopted

- **What:** ARWR's $60 close-based exit suspended Tue 10/13 through Wed 10/14 — webinar Wed 2:30 PM ET (interim ARO-MAPT data) is the most informative event on its calendar. Weak/bad data → exit Thu 10/15 regardless of price; good data → $60 line re-arms. Machinery: `RedLine` gained `suspended_until` (lapses automatically, revision recorded in the thesis decisions log); `checkin.py` and the hook honor it; the hook still watches ARWR for -5% intraday drops. Also adopted the near-tripwire judgment checklist into the morning session: for any holding within 5% of a red line, five questions in writing before the trigger — (1) what changed since the rule was set, (2) stock-specific or tape, (3) event binary-ness, (4) book pressure, (5) honest-broker test. Output: honor or rewrite with reasons. Thesis-break exits are never paused; no silent waivers.
- **Why:** Sreejith challenged the rule and it didn't survive: its premise ("weakest name, no catalyst") is stale post-STAR-entry; $60 is a round number, not a fundamental level; a stop firing on noise the day before the most informative event is badly designed. Judgment belongs in rule revision (written, reasoned, time-bounded) — not in waiving triggers.
- **Judged by:** whether Thursday's data call is made cleanly and the re-armed rule holds; QQQ ledger over subsequent weeks.

## 2026-10-12 — Hook respects close-based red lines; EXITED theses excluded from check-ins

- **What:** (1) The `circuit-watch` hook no longer fires intraday *approach* alerts for close-based red lines (ARWR's $60) — only the closing print is actionable there, so the approach wake was pure noise. Breach alerts still fire. Red lines carry a machine-readable `close_based` flag from the thesis YAML through `checkin.py --emit-watchlist` to the hook. (2) `checkin.py` now skips EXITED theses in both `--mode` evaluation and watchlist emission — INTC kept producing a stale `act` verdict after its exit.
- **Why:** A 10:40 ET hook wake on ARWR approach produced no actionable information (triaged and stood down); the worker correctly identified it as a false-positive class. Separately, the same wake surfaced the stale INTC verdict.
- **Judged by:** fewer no-op wakes in the hook log; no recurrence of stale verdicts on exited positions.

## 2026-10-11 — Rules are for contemplation; proactive improvement latitude

- **What:** Rules are hypotheses to question and evolve, never fixtures. Mu$e
  may make genuine improvements to the trading strategy, tools, and idea
  collection — or unship areas that aren't working — without per-change
  permission; changes aren't forced, and Sreejith is told when one is made.
- **Why:** Sreejith: "Existing rules are there for contemplation and are not
  set in stone. Better ideas or strategies can change rules." Same day: MAE/MFE
  is decision-only, not a report — analytics exist for Mu$e's judgment, not
  for telling the user.
- **Judged by:** whether rule changes from here on are written down with
  reasons (this file) and scored against QQQ — ruthless scorekeeping, not
  ceremony.

## 2026-10-09 — Unified check-in system; act under standing authority

- **What:** One routine (`checkin.py`), three trigger modes: scheduled (9:40
  full, 12:30 light), alert-driven (`circuit-watch` polling quotes every
  15 min market-hours against a daily watchlist), discretionary one-offs.
  Tripwires in `TRIGGERS.md`. Retired the midday-check falsification clause.
- **Why:** Sreejith: a rule without machinery is just words — the
  circuit-breaker needed real machinery, not a sentence. Then corrected the
  design: "Why ping me? You have autonomy to trade and act right?" → when a
  tripwire fires, decide and act under standing authority, then report in the
  what/why/exposure shape. Ping before acting only for things outside
  authority (account changes, new permissions) or blocked order placement.
- **Judged by:** whether breaches get acted on same-session vs. discovered at
  close review; whether user ever receives a "should I sell?" message again.

## 2026-10-08 — Order type is dynamic per-trade judgment; standing defensive posture

- **What:** Order type is no longer a fixed rule — market when fill certainty
  matters more than pennies, limit when spread/chasing risk dominates. Native
  stops, take-profits, and sell limits used defensively as the situation
  needs: scale out of runaway winners into strength, ratchet stops up behind
  winners, trim oversized positions. First exercise: a native INTC stop placed
  the same evening.
- **Why:** Sreejith: "doesn't have to be a single rule" — replaced the
  market-default rigidity with discretion; then explicitly authorized the
  defensive posture (sell limits named). The 9/21 INTC $114 limit that never
  filled when the price ran was the lesson behind the original default.
- **Judged by:** fill reliability on entries vs. spread cost; whether defensive
  exits preserve gains without chopping the book on noise.

## 2026-10-07 — Circuit-breaker rule

- **What:** If a holding breaks a red line violently intraday (stop level or
  >5% adverse move on news), act or surface it immediately rather than
  waiting for the 3:50 PM close review.
- **Why:** Sreejith pushed for midday decisions — waiting for the close
  review on a violent break is just words.
- **Judged by:** superseded by the 10/9 machinery; the rule earned its place
  the day it forced the check-in system to exist.

## 2026-10-06 — Removed the 10% of account cap on option positions

- **What:** Options sized on judgment now ("trade smartly"). Remaining
  guardrails: Level 2 only, ≥30 DTE unless deliberately event-driven, exit
  at −50% premium or on thesis break, covered calls only on keepers,
  same-name equity+option exposure counted together.
- **Why:** Sreejith removed the cap himself after the $1,500 deposit made
  the options program real (~$1,957 capital, 2–3 defined-risk positions
  viable); a cap at this size was preventing the program, not protecting it.
- **Judged by:** single-contract full loss as the sizing discipline; QQQ
  attribution on the options sleeve.

## 2026-09-28 — 10% cash buffer: hard rule → guideline

- **What:** Keep cash smartly, but deploy it when a genuine entry-bar idea
  appears.
- **Why:** Sreejith: a floor that's never touched is just a drag.
- **Judged by:** whether deployed cash beats QQQ over the subsequent quarter.

## 2026-09-21 — Market orders as the default

- **What:** Market orders for all entries/exits; limit orders only for narrow
  exceptions (extended-hours sessions where markets aren't permitted,
  illiquid names where spread risk exceeds non-fill risk, or explicitly
  documented price-discipline entries).
- **Why:** The INTC $114 price-discipline limit simply didn't fill when the
  price ran — non-fill is the cost of a limit.
- **Judged by:** superseded by the 10/8 dynamic-judgment rule; earned its
  place by stopping repeat non-fill misses in between.

## 2026-10-12 — Friday close-review: explicit native-stop weekend-coverage check

- **What:** The close-review session now carries an explicit checklist item:
  for every native stop / take-profit order that is the defense for a
  near-term tripwire, verify it will still be resting through the weekend
  (day/gfd orders placed Mon–Fri can expire Friday evening, leaving the
  weekend gap unguarded); re-place as needed for Monday morning coverage.
- **Why:** The INTC protective stop (stop-market, gfd, placed 10/8)
  expired Friday evening, so INTC gapped through the stop level over the
  weekend with no native order to catch it — the 15-minute circuit tripwire
  caught it at Monday's open (market exit near the mechanical -15%). The
  machinery worked, but the native layer that was supposed to be fastest was
  silently absent for 60 hours. A rule with a resting order is only real if
  the order is actually resting.
- **Judged by:** whether the next weekend gap near a tripwire is caught by a
  resting native order rather than the tripwire; the Friday close-review log
  should show the coverage check explicitly.

## 2026-10-14 — Mechanical "close below" red lines flagged close_based (watchlist/hook data fix)

- **What:** All mechanical "Close below" red lines in thesis YAMLs now carry
  `close_based: true` (CRWD, GRAB, MU, RKLB, SMMT — previously only ARWR's had
  the flag). The emitted hook watchlist now marks them close_based, so
  circuit-watch skips intraday *approach* alerts on them and fires only on
  actual close-basis breaches.
- **Why:** Morning session found the emitted watchlist marking RKLB/MU/etc.
  close-based lines as touch-triggered — the same false-positive class as the
  10/12 ARWR fix (intraday approach alerts on a line whose thesis explicitly
  says "close below"). An un-actionable alert is noise that trains everyone
  to ignore the system.
- **Also fixed:** GRAB.yaml's `position:` block sat after the decision log at
  end-of-file, so two consecutive decision-log appends (10/13 and 10/14)
  landed after `position:` and broke YAML parsing, failing checkin.py and
  check.py. `position:` now sits before `decisions:` — future appends are safe.
- **Also:** @MohanadInv nominated to x_pulse.py CANDIDATES (trending) —
  substantive CXMT/MU analysis matching our verified read, plus an 8-K-based
  CIFR convert model.
- **Judged by:** no intraday approach alerts on mechanical lines when price
  action stays above them intraday; the thesis tools keep passing YAML
  validation every morning.
