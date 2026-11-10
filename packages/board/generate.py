"""Generate Mu$e's Book board data from the thesis YAMLs.

Reads the private thesis files (the sessions' source of truth) plus the
paper ledger, and emits one JSON object the Book template renders. No LLM
in this loop: numbers come from the YAMLs and from prices the caller
passes in, so the page can't invent a label or drift a level.

Usage:
    python3 packages/board/generate.py \
      --prices '{"ACME": 10.00, "HELX": 25.00, "OPT": 16.00, "OPT_PREMIUM": 5.00}' \
      --account '{"total": 1000.00, "cash": 500, "qqq_gap_pp": 5.00}' \
      --as-of 2026-11-10 [--series series.json]

Output defaults to packages/board/board.private.json — PRIVATE. It holds
live stop levels and must never sync to the public repo (see README.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as date_cls
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from thesis.models import load_all  # noqa: E402

BENCHMARK_START = "2026-09-18"
FILL_RE = re.compile(r"FILL sell ([\d.]+) @ ([\d.]+)")


def _pct(a: float, b: float) -> float:
    return round((a - b) / b * 100, 1) if b else 0.0


def _pct_from_now(now: float, level: float) -> float:
    """Fall (or rise) needed from `now` to reach `level`, as % of now.

    This is the board's convention: "24% below now" at $10.00 vs a $7.60
    line is (10.00-7.60)/10.00, not /7.60. Distances are always % of now.
    """
    return round((now - level) / now * 100, 1) if now else 0.0


def _price_red_lines(thesis) -> list:
    return [r for r in thesis.red_lines if r.price_level is not None]


def _position_card(thesis, prices: dict) -> dict:
    p = thesis.position
    price = prices[thesis.ticker]
    card: dict = {
        "ticker": thesis.ticker,
        "name": thesis.name,
        "status": thesis.status,
        "price": price,
        "why": thesis.claim,
        "confirmation": thesis.confirmation,
    }
    if p.contracts:  # ---- single-leg option: two gauges ----
        exit_premium = round(p.premium_paid * 0.5, 2)  # -50% guardrail
        premium_now = prices.get(f"{thesis.ticker}_PREMIUM")
        stock_lines = _price_red_lines(thesis)
        reeval = stock_lines[0].price_level if stock_lines else None
        card.update({
            "kind": "option",
            "contracts": p.contracts,
            "strike": p.strike,
            "expiry": p.expiry,
            "premium_paid": p.premium_paid,
            "premium_now": premium_now,
            "pnl_pct": _pct(premium_now, p.premium_paid) if premium_now else None,
            "stock_gauge": {
                "now": price,
                "breakeven": p.breakeven,
                "pct_to_breakeven": _pct(p.breakeven, price) if p.breakeven else None,
                "reeval_line": reeval,
                "pct_to_reeval": _pct_from_now(price, reeval) if reeval else None,
            },
            "contract_gauge": {
                "now": premium_now,
                "exit_premium": exit_premium,
                "take_profit_premium": p.take_profit if p.take_profit_basis == "premium" else None,
                "pct_to_exit": _pct_from_now(premium_now, exit_premium) if premium_now else None,
            },
            # Primary exit is the premium line: it is what actually sells.
            "primary_exit": {"type": "premium", "level": exit_premium},
            "distance_to_primary_exit_pct": _pct_from_now(premium_now, exit_premium) if premium_now else None,
        })
    else:  # ---- equity: one stock gauge ----
        suspended = None
        for r in _price_red_lines(thesis):
            if r.suspended_until:
                suspended = r.suspended_until
        card.update({
            "kind": "equity",
            "shares": p.shares,
            "bought_at": p.blended_cost,
            "pnl_pct": _pct(price, p.blended_cost),
            "stock_gauge": {
                "now": price,
                "exit_line": p.stop,
                "exit_suspended_until": suspended,
                "take_profit": p.take_profit,
                "take_profit_qty": p.take_profit_qty or None,
                "pct_to_exit": _pct_from_now(price, p.stop) if p.stop else None,
                "pct_to_take_profit": _pct(p.take_profit, price) if p.take_profit else None,
            },
            "primary_exit": {"type": "stop", "level": p.stop},
            "distance_to_primary_exit_pct": _pct_from_now(price, p.stop) if p.stop else None,
        })
    return card


def _exit_log(theses) -> list[dict]:
    rows = []
    for t in theses:
        if t.status not in ("EXITED", "CLOSED"):
            continue
        for d in t.decisions or []:
            m = FILL_RE.search(d.text or "")
            if m:
                rows.append({
                    "ticker": t.ticker,
                    "closed": d.date,
                    "qty": float(m.group(1)),
                    "fill": float(m.group(2)),
                    "rule": (t.position.stop_note if t.position else "") or "",
                })
    rows.sort(key=lambda r: r["closed"], reverse=True)
    return rows[:7]


def build(prices: dict, account: dict, as_of: str, series: list | None) -> dict:
    theses = load_all()
    today = as_of or date_cls.today().isoformat()
    open_cards = []
    next_events = []
    for t in theses:
        if t.status not in ("INTACT", "WEAKENED"):
            continue
        if not t.position or (not t.position.shares and not t.position.contracts):
            continue
        if t.ticker not in prices:
            raise SystemExit(f"no price passed for open position {t.ticker}")
        open_cards.append(_position_card(t, prices))
        for kd in t.key_dates or []:
            if kd.date >= today:
                next_events.append({"ticker": t.ticker, "date": kd.date, "event": kd.event})
    # At-risk order: closest to the primary exit first.
    open_cards.sort(key=lambda c: (c["distance_to_primary_exit_pct"] is None,
                                   c["distance_to_primary_exit_pct"] or 0))
    next_events.sort(key=lambda e: e["date"])

    ledger = yaml.safe_load((ROOT / "packages/paper/ledger.yaml").read_text()) or {}
    paper = [{
        "ticker": e.get("ticker"),
        "flagged": str(e.get("flagged")),
        "ref_price": e.get("ref_price"),
        "ref_qqq": e.get("ref_qqq"),
        "status": e.get("status"),
        "thesis": (e.get("thesis") or "")[:160],
    } for e in ledger.get("entries", [])][:6]

    gap = account.get("qqq_gap_pp")
    spy_gap = account.get("spy_gap_pp")
    board = {
        "generated_at": today,
        "as_of": today,
        "private": True,
        "note": "Generated from thesis YAMLs — never commit to the public repo.",
        "scorecard": {
            "account_total": account.get("total"),
            "cash": account.get("cash"),
            "benchmark": "QQQ",
            "benchmark_start": BENCHMARK_START,
            "qqq_gap_pp": gap,
            "spy_gap_pp": spy_gap,
            "gap_sentence": (
                f"Account is {abs(gap):.2f}pp "
                f"{'ahead of' if gap and gap >= 0 else 'behind'} QQQ since Sep 18."
                if gap is not None else None),
            "today": {
                "day_change_usd": account.get("day_change_usd"),
                "day_gap_vs_qqq_pp": account.get("day_gap_vs_qqq_pp"),
                "next_event": next_events[0] if next_events else None,
            },
        },
        "positions": open_cards,
        "race": {"status": "wired" if series is not None else "not_wired",
                 "series": series or []},
        "exits": _exit_log(theses),
        "paper": paper,
        "watch": [],
        "next_events": next_events,
    }
    return board


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True, help="JSON: {TICKER: price, TICKER_PREMIUM: premium}")
    ap.add_argument("--account", required=True, help="JSON: {total, cash, qqq_gap_pp, ...}")
    ap.add_argument("--as-of", default=date_cls.today().isoformat())
    ap.add_argument("--series", default=None, help="optional JSON file with race series points")
    ap.add_argument("--out", default=str(HERE / "board.private.json"))
    args = ap.parse_args()
    series = json.loads(Path(args.series).read_text()) if args.series else None
    board = build(json.loads(args.prices), json.loads(args.account), args.as_of, series)
    Path(args.out).write_text(json.dumps(board, indent=2) + "\n")
    print(f"wrote {args.out}: {len(board['positions'])} positions, "
          f"{len(board['exits'])} exits, {len(board['paper'])} paper entries")


if __name__ == "__main__":
    main()
