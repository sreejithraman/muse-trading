"""Ledger analytics — thin, honest math on the machine-written record.

Two halves:
  1. Open-position analytics (the useful half today): for each thesis,
     entry date + blended cost -> return %, days held, MAE/MFE from
     daily bars since entry, and QQQ-relative attribution over the hold.
  2. Closed-trade framework: win rate by setup, avg win/loss, holding
     periods — computed from trades.yaml. With no closed strategy
     trades yet it says so plainly instead of inventing a track record.

MAE/MFE note: blended cost with a single entry date is an approximation
when a position was added to (e.g. SMMT). Directionally right, not
accounting-grade. The day-1 liquidation batch (16 exits, -$12.80) is
recorded in trades.yaml as ONE aggregate row — per-trade cost basis for
inherited positions is unavailable, and fabricating it would be worse
than useless.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "thesis"))
sys.path.insert(0, str(ROOT / "packages" / "data"))

from bars import fetch_daily  # noqa: E402
from models import load_all  # noqa: E402


def _bars_by_date(bars: list[dict]) -> dict[str, dict]:
    return {b["date"]: b for b in bars}


def open_position_stats() -> list[dict]:
    """Per-thesis MAE/MFE/hold-period/QQQ-relative stats. Read-only."""
    theses = load_all()
    qqq = _bars_by_date(fetch_daily("QQQ", range_="6mo"))
    out = []
    for t in theses:
        pos = t.position
        if not pos or not pos.blended_cost:
            continue
        entry = t.opened
        bars = [b for b in fetch_daily(t.ticker, range_="6mo") if b["date"] >= entry]
        if not bars:
            continue
        cost = pos.blended_cost
        px = bars[-1]["close"]
        rets = [(b["close"] / cost - 1) * 100 for b in bars]
        maes = [(b["low"] / cost - 1) * 100 for b in bars]
        mfes = [(b["high"] / cost - 1) * 100 for b in bars]
        days = (date.today() - date.fromisoformat(entry)).days
        # QQQ over the same hold
        q_entry = [v for d, v in sorted(qqq.items()) if d >= entry]
        q_ret = ((q_entry[-1]["close"] / q_entry[0]["close"] - 1) * 100
                 if len(q_entry) > 1 else None)
        cur = rets[-1]
        out.append({
            "ticker": t.ticker,
            "status": t.status,
            "days_held": days,
            "return_pct": round(cur, 1),
            "mae_pct": round(min(maes), 1),
            "mfe_pct": round(max(mfes), 1),
            "qqq_pct": round(q_ret, 1) if q_ret is not None else None,
            "excess_pp": round(cur - q_ret, 1) if q_ret is not None else None,
        })
    return sorted(out, key=lambda r: r["excess_pp"] if r["excess_pp"] is not None else -999)


def closed_trade_summary(path: str | Path | None = None) -> dict:
    """Win rate etc. from trades.yaml. Honest about small samples."""
    path = Path(path or Path(__file__).resolve().parent / "trades.yaml")
    trades = yaml.safe_load(path.read_text())["trades"]
    indiv = [t for t in trades if not t.get("aggregate")]
    agg_pnl = sum(t["realized_pnl"] for t in trades if t.get("aggregate"))
    if not indiv:
        return {"n": 0, "note": "no closed strategy trades yet",
                "aggregate_pnl": round(agg_pnl, 2)}
    wins = [t for t in indiv if t["realized_pnl"] > 0]
    by_setup: dict[str, list] = {}
    for t in indiv:
        by_setup.setdefault(t.get("setup", "unspecified"), []).append(t)
    return {
        "n": len(indiv),
        "win_rate": round(len(wins) / len(indiv) * 100, 1),
        "avg_win": round(sum(t["realized_pnl"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["realized_pnl"] for t in indiv if t["realized_pnl"] <= 0)
                          / max(1, len(indiv) - len(wins)), 2),
        "by_setup": {s: {"n": len(v),
                         "win_rate": round(sum(1 for t in v if t["realized_pnl"] > 0) / len(v) * 100, 1)}
                     for s, v in by_setup.items()},
        "aggregate_pnl": round(agg_pnl + sum(t["realized_pnl"] for t in indiv), 2),
    }
