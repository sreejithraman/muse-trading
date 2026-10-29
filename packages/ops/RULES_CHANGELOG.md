# Rule change log

The operation's rules are hypotheses, not fixtures. When a rule changes,
record it here: date, what changed, why, and how we'll know whether the new
one earned its place. A rule that changed without a written reason is just a
mood — the QQQ ledger judges whether the change worked, over subsequent
weeks of session scoring and attribution, not over one trade.

Newest entries go at the top.

---

## 2026-10-16 (afternoon) — checkin.py blinded by malformed thesis YAML; self-caught and fixed

- **What:** The 3:10 PM hook worker appended decision records at end-of-file in CRWD.yaml and MU.yaml, after the `confirmation:`/`position:` tail keys — breaking yaml.safe_load and crashing checkin.py on startup (load_all throws on any single bad file). The alert-driven system was blind ~3:10–3:48 PM. Fixed by moving the stray entries into their `decisions:` sections, validated every thesis file parses, re-ran checkin cleanly (SMMT/CRWD/MU alerts evaluated). Backups kept at /tmp/CRWD.yaml.bak, /tmp/MU.yaml.bak. AGENTS.md lesson added: decision entries insert immediately before the `confirmation:` line, never at EOF, then re-validate.
- **Why:** A single malformed file took down the whole tripwire layer — the failure mode the 10/12 false-positive fix didn't cover. Same class as the 10/12 self-caught fix: the machinery repairing itself.
- **Judged by:** no checkin crashes; hook log stays clean.

---

## 2026-10-16 — Tool ablation (paper rethink commitment): utility bar applied, three inputs demoted

- **What:** Ran the 2026-10-14 commitment: the paper's utility bar (keep only what demonstrably changed a decision this month) applied to every morning tool/input. KEEP: check-in routine + circuit-watch hook (INTC dead-stop exit 10/12); thesis YAMLs + check.py board (drove ARWR/RKLB/MU calls); near-tripwire checklist (written ARWR 10/12+10/14, MU 10/15); pre-exit new-information check (live ARWR 10/14, fired as written); record_fill/record_postmortem (post-mortems filed for INTC/ARWR/RKLB); vol-aware sizing (standing method since 10/14); mechanical take-profit brackets (GRAB native TP 10/14); idea inbox (routed USAR out, SOFI in → bought 10/13); X digest (QuiverQuant flags → no-scraper verdict + NANC paper entry; candidate nominations); watchlist regeneration (feeds the hook); MAE/MFE (already on-demand only); Feed prompt sync; paper book (first review 11/1, not yet judgeable). DEMOTE: Form 4 scanner daily → weekly (no cluster changed a decision in ~2 weeks of daily runs; fold into Sunday sweep, re-grade in a month); TV screener daily → weekly Monday pre-open (no screen idea ruled in this month); TA daily regime print → on-demand when setting/judging a stop (ATR levels earned their keep at entry; the daily print changed no call). EXEMPT: catalyst sweep (first run 10/18 — judge after it runs). Fixed in the same pass: screener ran on system python which lost the tvscreener module (VM replacement wipes /usr); new persistent venv at `~/workspace/trading-tools/.venv`, morning cron now calls the screener through it.
- **Why:** The paper's best-performing template was the most restrained; compute that never changes a decision is the agent admiring its own machinery.
- **Judged by:** demoted inputs stay demoted unless a weekly run changes a decision; the falsification condition (mid-Jan 2027) judges the survivors.

---

## 2026-10-15 (morning) — checkin.py excludes CLOSED too; exited names can't re-fire the hook

- **What:** `checkin.py` now excludes both `CLOSED` and `EXITED` theses in `--mode` evaluation and `--emit-watchlist` (was: EXITED only). Regenerated the live watchlist: ARWR, RKLB, INTC removed.
- **Why:** A 9:45 AM hook wake fired breach alerts on ARWR and RKLB — both already exited at 9:44 AM by the morning session on the 10/14 close-review decisions (fills recorded, postmortems written). Root cause: the session's fill flow writes `status: CLOSED` transiently and only later finalizes to `EXITED`; the 10/12 filter (EXITED-only) let CLOSED theses through, and the 9:46 AM watchlist was emitted inside that window — the same false-positive class the 10/12 fix meant to kill, recurring through the transient status. During the investigation the worker briefly swapped the filter to CLOSED-only, which was wrong (steady-state is EXITED — INTC/ARWR/RKLB all carry it); caught and corrected before it shipped.
- **Judged by:** no hook wakes on exited names; hook log stays clean on exit mornings.

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

## 2026-10-14 — Pre-exit new-information check (close-review step)

- **What:** The close review now carries a standing step: when an armed
  mechanical exit line is tested at today's close, confirm no material new
  information arrived since the morning's near-tripwire checklist before
  honoring the trigger. New information = facts the last judgment didn't have
  (e.g. an afternoon webinar Q&A, a post-checklist news release). Price
  movement alone is never new information and never reopens the call. If
  material new info exists, re-run the checklist with it and log the outcome;
  otherwise the rule fires as written. This is a scan, not a re-deliberation —
  the default is execution.
- **Why:** Sreejith's 10/14 proposal — judgment runs in the morning session,
  triggers fire at the close, and information can land in between (the ARWR
  webinar Q&A runs 2:30 PM, after the morning checklist, on the same day the
  re-armed $60 line is tested). Without the check, the close could execute on
  a stale judgment; without the fence, every exit becomes a 3:59 PM
  re-deliberation under loss pressure and mechanical exits die by hesitation.
- **Judged by:** exits execute on schedule when no new info arrived; when
  genuinely new info lands between checklist and close, the decision log shows
  the checklist re-run with it.

## 2026-10-16 — Ablation: the paper's utility bar applied to every morning input

- **KEEP (one line of evidence each):** unified check-in — its ACT verdict
  (10/15: ARWR/RKLB/MU flagged) organized a two-exit session, and the
  verdict is the session's starting point; thesis check.py — its 5%-within-
  red-line flag triggers written deliberations and its dates column surfaces
  SMMT Q3 Mon 10/19; X catalysts — the only digest section that produced a
  rule-in this month (SOFI, 10/13); X news — the Sep-PPI-blowout framing
  shaped the 10/15 MU deliberation; X trending — the CRWV-credit thread
  explained today's AI de-risking tape and the RKLB-slip thread validated
  the 10/15 exit same-day; MAE/MFE excursion as decision-gated — ran 10/12
  (ARWR) and 10/15 (MU), skipped 10/16 when it couldn't change the verdict
  (the gate working, not the ritual); vol-aware sizing + mechanical brackets
  + provenance ledger (Thesis.record_fill/postmortem) — the paper's core,
  no live test yet for sizing (no entries since 10/14) so judgment reserved
  to the January ledger; circuit-watch hook — fired on INTC's gap (10/12
  exit) and its 10/12 false-positive class was self-fixed; candidate-tier
  handle curation — @JasonL_Capital earned promotion today (4 rule-in
  signals in 4 days), the mechanism demonstrably changed curation behavior.
- **DEMOTE:** X flow section — OUT of the daily digest: zero rule-ins in all
  of October, every entry this month came from catalysts; available via
  `x_pulse.py --sections flow|all` for the weekly Sunday sweep (the digest
  cron body still says "four queries" — stale text, flagged). TA test_drive
  — from daily ritual to on-demand only when judging a stop/trim/exit: every
  session this month merely confirmed fixed stops bind vs 3xATR and no trade
  changed on TA output. Screener — from daily to weekly + on-demand:
  "no book holdings in top-30, nothing vets" every single day this month;
  the momentum discipline survives at lower cadence. Form 4 scan —
  RECOMMENDED weekly (needs a schedule change: not executed here per the
  scheduler rules): zero rule-ins this month, every cluster ruled out daily,
  clusters are stale-dated by nature (GME traded 9/8, filed 10/13).
- **FIXES SHIPPED TODAY:** (1) checkin.py fetch_quotes now refreshes the
  OAuth token on "JWT verification failed" and retries once — the 4th
  overnight-expiry occurrence (9/24, 10/1, 10/8, 10/16) is the last one the
  check-in path has to suffer manually; (2) TA test_drive.py now reads
  active theses for tickers + fixed stops instead of a hardcoded list —
  it was still printing INTC/ARWR/RKLB (exited) as stale noise; (3)
  @JasonL_Capital promoted from CANDIDATES to HANDLES[catalysts].
- **IDENTIFIED, NOT SHIPPED:** Form 4 daily→weekly cadence (schedule change
  on a different cron — flagged for the main agent, not executed); the
  9:40 session body still names daily screen/TA/Flow 4 — future sessions
  should read this changelog as overriding (the body itself ordered the
  ablation); feed.prompt_get/prompt_update still unavailable to workers —
  holdings changed 10/13 and 10/15, both flagged for the main agent, the
  strategy.md standing note remains the workaround.
- **Why:** DXRG 2609.05663's sharpest transferable finding is restraint —
  the most restrained template performed best. Anything that runs daily but
  never changes a decision is attention tax, not edge.
- **Judged by:** fewer daily inputs with no lost decisions — if a weekly
  Form 4/flow/screen ever produces a rule-in the daily set would have
  missed, that decision goes in the log and the cadence is revisited.

## 2026-10-14 — Paper rethink: vol-aware sizing, mechanical brackets, provenance ledger, falsification condition

- **What:** Full operation rethink against DXRG 2609.05663 ("What LLM Trading
  Agents Actually Do in Production"), at Sreejith's direction. Built: (1)
  `packages/sizing/size.py` — ATR-based sizing (size inversely to realized
  vol, QQQ-regime governor halves size in high-vol regimes, 2%-of-equity risk
  cap); the morning session now sizes in code, not on judgment. (2)
  Mechanical take-profit brackets on every position: half at 2x the stop
  distance from cost; GRAB native sell limit (33 sh @ $3.88, gtc) placed and
  confirmed 2026-10-14; fractional positions session-monitored via TP-DIST;
  SOFI premium-double trigger (session must decide); SMMT/ARWR exempt as
  binary catalysts. (3) `Thesis.record_fill()` decision-provenance ledger and
  `record_postmortem()`, wired into the morning entry step and the close
  review. (4) Pre-registered `confirmation` observable backfilled on all
  theses. Kept deliberately: the operating layer, no-leverage structure, QQQ
  ledger, changelog, low frequency, entry bar.
- **Why:** The paper's firmest findings map directly onto our defects:
  volatility-blind sizing was their largest measured defect; a fixed bracket
  beat every discretionary exit (+39 bps/position); agent fixed effects absorb
  60% of variance, so the mitigation is less of the agent at execution.
  Rebuild-from-scratch rejected per the paper's own #1 finding (the operating
  layer is the valuable part; strategy text is cheap).
- **Judged by:** Friday 2026-10-16 ablation applies the paper's utility bar
  (keep only tools that demonstrably change behavior). FALSIFICATION
  CONDITION: if the cumulative ledger still trails QQQ three months out
  (~mid-Jan 2027), the paper's "no edge" finding is probably us — shrink
  gross exposure and stop adding machinery. Judge the new rules by whether
  they move the ledger, not by whether they feel rigorous.

## 2026-10-19 — SMMT stop-suspension window extended 11/13 -> 11/16 (judgment in rule revision)

- **What:** The $14.46 mechanical stop suspension now runs through Mon 2026-11-16 (was Fri 2026-11-13). Re-armed rule: any close at/below $14.46 from 11/16 onward exits the full position next session, market. The thesis-break line (FDA rejection/CRL on the 11/14 PDUFA) stands unchanged and is never paused.
- **Why:** The 10/12 pause was built around the PDUFA binary but the window ended 11/13, one day before the Sat 11/14 PDUFA — a close below the line on PDUFA-eve Friday would fire the mechanical rule into the very event the pause was designed to suspend. The 10/18 catalyst sweep flagged the one-day gap; the 10/19 morning session closed it. Pause windows are set by judgment per case, never a fixed number: 11/16 covers the binary plus one session of market reaction.
- **Judged by:** whether the re-armed 11/16 rule fires or is honored cleanly at the first close test after re-arming.

## 2026-10-26 — Falsification condition retired (mid-Jan 2027 shrink rule removed)

- **What:** The 2026-10-14 falsification condition — shrink gross exposure if the ledger still trails QQQ ~mid-Jan 2027 — is retired and no longer in force.
- **Why:** Sreejith directed its removal on 2026-10-26. It was Mu$e's proposal in the Oct 14 paper-rethink build, not Sreejith's own rule; the QQQ ledger and scoring continue, but no automatic shrink deadline is attached to them.
- **Judged by:** the ledger keeps being scored against QQQ; no shrink action is triggered by any date.
