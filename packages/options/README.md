# packages/options — options fit-checker

Single-leg idea evaluation for a Level 2 book (long calls/puts only —
no spreads, no naked anything). Evaluates; never trades.

## What it does (`fit.py`)

Given ticker, kind, strike, expiry, and quoted premium:

- **Fair value** at historical vol (60d annualized) vs the quote
- **IV back-out** from the premium → IV vs HV (are we buying inflated
  vol into an event?)
- **Greeks** (delta, gamma, theta/day, vega), **breakeven**,
  **max loss**, theta burn as % of premium per day
- **Guardrails** from the book's standing rules:
  - premium ≤ 10% of account at cost
  - ≥ 30 DTE unless explicitly flagged event-driven
  - exit at -50% premium or on thesis break (reminder, not automation)

## Math (`bs.py`)

Pure-python Black-Scholes, verified against textbook values
(S=100/K=100/T=1/r=5%/σ=20% → 10.45, Δ 0.637, IV back-out 0.20).
Correct-enough for fit-checks with zero install risk; opengreeks
(Rust) is the planned upgrade if we ever need surface-accurate IV.

## Usage

```bash
python3 test_drive.py
```

Illustrative run (2026-10-06, hypothetical $1.50 premium — not a
trade): SMMT Nov $20 call showed HV 70% vs IV 99% (vol bid into the
FDA binary), fair value $0.84 vs $1.50 quote, and the 10% guardrail
firing ($150 > $46 max) — the tool mechanically explains why
single-leg options don't fit this account size yet.
