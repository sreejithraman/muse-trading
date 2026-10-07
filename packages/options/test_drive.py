#!/usr/bin/env python3
"""Test-drive the options fit-checker.

1. Black-Scholes sanity check against a textbook value.
2. ILLUSTRATIVE fit-check (hypothetical premium, NOT a trade idea):
   SMMT Nov $20 call — shows how the guardrails treat a single-leg
   idea at this account size.
Read-only demo; evaluates, never trades.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bs import greeks, implied_vol, price  # noqa: E402
from fit import fit_check, report  # noqa: E402


def main() -> int:
    # textbook: S=100 K=100 T=1 r=5% vol=20% -> call ~10.45
    px = price(100, 100, 1.0, 0.05, 0.20, "call")
    g = greeks(100, 100, 1.0, 0.05, 0.20, "call")
    iv = implied_vol(10.45, 100, 100, 1.0, 0.05, "call")
    print(f"BS sanity: call={px:.2f} (want ~10.45), "
          f"delta={g['delta']} (want ~0.64), IV back-out={iv} (want ~0.20)")
    assert abs(px - 10.45) < 0.05, "BS price off"
    assert abs(iv - 0.20) < 0.005, "IV back-out off"
    print("BS math OK\n")

    print("ILLUSTRATIVE fit-check (hypothetical $1.50 premium — not a trade):")
    fc = fit_check("SMMT", "call", strike=20.0, expiry="2026-11-21",
                   premium=1.50, account_value=459.0)
    print(report(fc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
