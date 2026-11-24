#!/usr/bin/env python3
"""Standing spiky-events scan (rule 2026-11-24 machinery).

Recurring version of the one-off 2026-11-24 draft's method: 3-month daily
bars via packages/data/bars.py, drawdown vs the 3-month high, washout low
from the last 5 sessions. Runs weekday mornings before the 9:40 session and
refreshes the spiky watchlist draft the session reads.

The scan is mechanical — it ranks drawdowns. It does NOT rule names in or
out, does NOT write thesis files, and does NOT auto-queue anything to the
idea inbox. The session judges every name against the entry bar.

Catalyst dates are the previously verified ones (from the 2026-11-24 draft);
a name with no catalyst on file is flagged "needs verification" and the cron
worker checks it via browser.search before the session. A catalyst date that
has passed drops off the list.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_cls
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
import bars  # noqa: E402

OUT_DIR = (Path.home() / "workspace/goals/agentic-account-trading-operation"
           / "hidden_files")

# Fixed universe from the 2026-11-24 draft (drawdown + event hunters only).
UNIVERSE = ["MU", "MRVL", "DELL", "ORCL", "MLYS", "AMD", "AVGO", "META",
            "PLTR", "ARM", "SMCI", "COIN", "UNH", "ANAB", "CRWD", "NVDA"]

# Catalyst dates verified in the 2026-11-24 draft (company releases / Zacks /
# SEC filings). None = no catalyst on file — needs verification, not assumed.
VERIFIED_CATALYSTS: dict[str, tuple[str, str]] = {
    "MU": ("2026-12-17", "Q1 FY27 earnings"),
    "MRVL": ("2026-12-01", "Q3 FY27 earnings, after close"),
    "ORCL": ("2026-12-14", "Q2 FY27 earnings, after close"),
    "MLYS": ("2026-12-22", "PDUFA lorundrostat"),
    "AMD": ("2026-12-01", "UBS Global Technology and AI Conference (weak)"),
    "AVGO": ("2026-12-09", "earnings (estimated)"),
    "NVDA": ("2026-12-01", "Huang House interview"),
    "DELL": ("2026-11-24", "Q3 FY27 earnings, after close"),
    # Verified 2026-11-24 by the spiky-scan worker (company release, not the
    # original draft): CRWD Q3 FY27 results AMC Dec 1, 2026 — Business Wire
    # release via Nasdaq, confirmed on Zacks earnings calendar.
    "CRWD": ("2026-12-01", "Q3 FY27 earnings, after close"),
}

DRAW_DOWN_PCT = -25.0   # vs 3-month high: the spikiness bar
MONTH_PCT = -15.0       # 1-month slide: the secondary bar


def scan_symbol(sym: str) -> dict | None:
    """Drawdown math for one name, or None on a data gap (never crash)."""
    try:
        daily = bars.fetch_daily(sym, range_="3mo")
    except Exception as e:  # noqa: BLE001
        print(f"(bars failed for {sym}: {e})", file=sys.stderr)
        return None
    if len(daily) < 30:
        return None
    high = max(b["high"] for b in daily)
    last = daily[-1]
    month_ago = daily[-22]["close"] if len(daily) >= 22 else daily[0]["close"]
    recent = daily[-5:]
    wash = min(recent, key=lambda b: b["low"])
    return {
        "symbol": sym,
        "close": round(last["close"], 2),
        "date": last["date"],
        "high_3mo": round(high, 2),
        "drawdown_pct": round((last["close"] / high - 1) * 100, 1),
        "month_pct": round((last["close"] / month_ago - 1) * 100, 1),
        "washout_low": round(wash["low"], 2),
        "washout_date": wash["date"],
        "washout_close": round(wash["close"], 2),
    }


def classify(row: dict, today: str) -> str:
    """spiky | watch | cut — the bar is the bar, the session judges the rest."""
    cat = VERIFIED_CATALYSTS.get(row["symbol"])
    cat_ok = bool(cat and cat[0] >= today)
    spiky = row["drawdown_pct"] <= DRAW_DOWN_PCT or row["month_pct"] <= MONTH_PCT
    if spiky and cat_ok:
        return "spiky"
    if spiky:
        return "watch"  # deep drawdown, no verified catalyst on file
    return "cut"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = date_cls.today().isoformat()
    rows = []
    for sym in UNIVERSE:
        r = scan_symbol(sym)
        if r:
            r["catalyst"] = VERIFIED_CATALYSTS.get(sym)
            r["class"] = classify(r, today)
            rows.append(r)
    rows.sort(key=lambda r: r["drawdown_pct"])
    summary = {"date": today, "rows": rows}
    print(json.dumps(summary, indent=1))

    spiky = [r for r in rows if r["class"] == "spiky"]
    watch = [r for r in rows if r["class"] == "watch"]
    cut = [r for r in rows if r["class"] == "cut"]

    lines = [f"# Spiky-events watchlist — {today}", "",
             "**Status:** DRAFT ONLY. No thesis files written, no orders placed, "
             "nothing added to the idea inbox. The 9:40 session rules each name "
             "in or out against the entry bar (fear + dated/live reason + red "
             "line).",
             "",
             "Method: 3-month daily bars (Yahoo via `packages/data/bars.py`), "
             "drawdown vs the 3-month high; washout low = lowest low of the "
             "last 5 sessions. Catalyst dates are the previously verified ones; "
             "a name with no catalyst on file needs verification before the "
             "session judges it.",
             "",
             "Entry shape (all names): stabilization only, never gap-chasing — "
             "see `packages/thesis/pending/README.md` for the definition. "
             "Red-line anchor is the washout low while it holds.",
             ""]
    for title, group in (("Spiky — drawdown + verified catalyst in window", spiky),
                         ("Watch — deep drawdown, catalyst unverified", watch)):
        lines.append(f"## {title}")
        lines.append("")
        if not group:
            lines.append("(none)")
            lines.append("")
            continue
        for r in group:
            cat = r["catalyst"]
            cat_s = f"{cat[1]} {cat[0]}" if cat else "NO CATALYST ON FILE — verify"
            lines.append(
                f"- **{r['symbol']}** ${r['close']:.2f} — drawdown "
                f"{r['drawdown_pct']:.1f}% vs 3-mo high ${r['high_3mo']:.2f}, "
                f"{r['month_pct']:+.1f}% in a month; washout low "
                f"${r['washout_low']:.2f} ({r['washout_date']}), washout close "
                f"${r['washout_close']:.2f}; catalyst: {cat_s}")
        lines.append("")
    lines.append("## Cut — fails the bar")
    lines.append("")
    for r in cut:
        lines.append(f"- {r['symbol']} ${r['close']:.2f} — drawdown "
                     f"{r['drawdown_pct']:.1f}% (bar {DRAW_DOWN_PCT:.0f}%), "
                     f"{r['month_pct']:+.1f}% in a month")
    lines.append("")
    doc = "\n".join(lines)
    if args.dry_run:
        print("--- draft that would be written ---")
        print(doc)
        return 0
    out = OUT_DIR / f"spiky-watchlist-draft-{today}.md"
    out.write_text(doc)
    print(f"wrote {out} ({len(spiky)} spiky, {len(watch)} watch, "
          f"{len(cut)} cut)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
