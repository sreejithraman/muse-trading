#!/usr/bin/env python3
"""Test-drive screen.py: run the morning-idea screen, print the top 15.

Read-only demo — no brokerage touch. Also cross-checks whether any of
the book's current holdings surface in the screen (sanity, not a signal).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen import COLS, fetch_universe, score  # noqa: E402

BOOK = {"MU", "INTC", "CRWD", "SMMT", "ARWR", "RKLB"}


def main() -> int:
    print("fetching universe (TradingView scanner)…")
    df = fetch_universe()
    print(f"{len(df)} liquid names")
    ranked = score(df)

    show = ["ticker", "name", "price", "perf_1w", "rvol",
            "day_change", "gap_pct", "earnings"]
    cols = [COLS[k] for k in show]
    top = ranked.head(15)
    pd_opts = {"float_format": lambda x: f"{x:.2f}"}
    with pd.option_context("display.width", 160, "display.max_columns", 12,
                           "display.float_format", pd_opts["float_format"]):
        print(top[cols + ["score", "catalyst_flag"]].to_string(index=False))

    hits = [t for t in top[COLS["ticker"]].head(30)
            if str(t).replace("NASDAQ:", "").replace("NYSE:", "") in BOOK]
    print(f"\nbook holdings in top-30: {hits or 'none'}")
    print("\nScreen surfaces ideas; it doesn't decide. Catalyst judgment is human.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
