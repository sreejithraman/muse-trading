#!/usr/bin/env python3
"""Test-drive analytics.py: open-position MAE/MFE/hold/QQQ attribution,
plus the closed-trade summary. Read-only demo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analytics import closed_trade_summary, open_position_stats  # noqa: E402


def main() -> int:
    print("OPEN POSITIONS — excursion & attribution since entry")
    print(f"{'TKR':<5}{'DAYS':>5}{'RET%':>7}{'MAE%':>7}{'MFE%':>7}"
          f"{'QQQ%':>7}{'EXC.pp':>8}  STATUS")
    print("-" * 62)
    for r in open_position_stats():
        print(f"{r['ticker']:<5}{r['days_held']:>5}{r['return_pct']:>+6.1f}%"
              f"{r['mae_pct']:>+6.1f}%{r['mfe_pct']:>+6.1f}%"
              f"{r['qqq_pct']:>+6.1f}%{r['excess_pp']:>+7.1f}  {r['status']}")
    print("-" * 62)
    print("MAE = worst intraday dip vs cost | MFE = best intraday run vs cost")
    s = closed_trade_summary()
    print(f"\nCLOSED TRADES: n={s['n']} — {s['note']}"
          f" | aggregate realized ${s['aggregate_pnl']:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
