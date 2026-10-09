#!/usr/bin/env python3
"""Unified position check-in: the one routine every session and alert uses.

Loads thesis red lines, pulls live quotes, and emits a verdict per holding:
  act     - price at or below a price red line (thesis says exit/decide NOW)
  alert   - within 2% above a red line, or intraday move <= -5% (needs triage)
  quiet   - checked, everything within bounds
  unknown - quotes unavailable for this holding (data failure, NOT a clean bill)

`data_quality` is ok / degraded / none depending on how many symbols got
quotes. A blind read must never be reported as "all clear" — see TRIGGERS.md.

Modes:
  --mode light   quotes + red lines + verdict        (midday check, hook worker)
  --mode full    light + per-holding context lines   (morning session starting point)
  --emit-watchlist PATH
                 write {"levels":[{symbol, red_lines:[...], warn_pct}], ...}
                 for the circuit-watch hook's 15-min poll

Exit code: 0 always (verdict is data, not failure). Never places orders.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thesis"))
from models import load_all  # noqa: E402

MCP_PY = str(Path.home() / "workspace/robinhood-mcp/.venv/bin/python")
MCP_TOOL = str(Path.home() / "workspace/robinhood-mcp/mcp_tool.py")

ALERT_PCT = 2.0   # within this % above a red line -> alert
DROP_PCT = -5.0   # intraday move at or below this -> alert


def fetch_quotes(tickers: list[str]) -> dict[str, dict]:
    """Live quotes via Robinhood MCP. Returns {symbol: {price, prev_close}}."""
    env = dict(os.environ, NO_PROXY="", no_proxy="")
    try:
        out = subprocess.run(
            [MCP_PY, MCP_TOOL, "get_equity_quotes", json.dumps({"symbols": tickers})],
            capture_output=True, text=True, timeout=60, env=env,
        )
        data = json.loads(out.stdout).get("data", {}).get("results", [])
        quotes = {}
        for r in data:
            q = r.get("quote", {})
            sym = q.get("symbol", "")
            px = q.get("last_trade_price") or q.get("last_non_reg_trade_price")
            if px:
                quotes[sym] = {
                    "price": float(px),
                    "prev_close": float(q.get("previous_close") or 0) or None,
                }
        return quotes
    except Exception as e:  # noqa: BLE001
        print(f"(quote fetch failed: {e})", file=sys.stderr)
        return {}


def evaluate() -> dict:
    theses = load_all()
    tickers = [t.ticker for t in theses]
    quotes = fetch_quotes(tickers)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    holdings = []
    worst = "quiet"
    rank = {"quiet": 0, "unknown": 1, "alert": 2, "act": 3}

    for t in theses:
        q = quotes.get(t.ticker, {})
        px = q.get("price")
        prev = q.get("prev_close")
        verdict, reasons = "quiet", []
        dist = {}
        if not px:
            verdict, reasons = "unknown", ["quote fetch failed"]
        else:
            for rl in t.red_lines:
                if rl.price_level:
                    d = (px / rl.price_level - 1) * 100
                    dist[rl.trigger[:48]] = round(d, 2)
                    if px <= rl.price_level:
                        verdict, reasons = "act", [f"at/below red line: {rl.trigger[:60]}"]
                        break
                    if d <= ALERT_PCT:
                        verdict = "alert"
                        reasons.append(f"{d:.1f}% above red line: {rl.trigger[:48]}")
            if prev:
                move = (px / prev - 1) * 100
                if move <= DROP_PCT and verdict != "act":
                    verdict = "alert"
                    reasons.append(f"intraday {move:.1f}%")
        holdings.append({
            "ticker": t.ticker,
            "price": round(px, 2) if px else None,
            "verdict": verdict,
            "reasons": reasons,
            "red_line_dist_pct": dist,
            "status": t.status,
        })
        if rank[verdict] > rank[worst]:
            worst = verdict

    got = sum(1 for h in holdings if h["price"] is not None)
    data_quality = "ok" if got == len(holdings) else ("degraded" if got else "none")

    return {"as_of_utc": now, "date": date.today().isoformat(),
            "overall": worst, "data_quality": data_quality,
            "holdings": holdings}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="light", choices=["light", "full"])
    ap.add_argument("--emit-watchlist", default=None)
    args = ap.parse_args()

    if args.emit_watchlist:
        theses = load_all()
        levels = []
        for t in theses:
            pls = sorted({rl.price_level for rl in t.red_lines if rl.price_level})
            if pls:
                levels.append({"symbol": t.ticker, "red_lines": pls,
                               "warn_pct": ALERT_PCT, "drop_pct": DROP_PCT})
        Path(args.emit_watchlist).parent.mkdir(parents=True, exist_ok=True)
        Path(args.emit_watchlist).write_text(json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "levels": levels}, indent=1))
        print(f"wrote {args.emit_watchlist} ({len(levels)} symbols)")
        return 0

    rep = evaluate()
    if args.mode == "full":
        print(f"# check-in {rep['date']} ({rep['as_of_utc']}) overall: {rep['overall'].upper()}")
        for h in rep["holdings"]:
            px = f"${h['price']:.2f}" if h["price"] else "(no quote)"
            why = (" — " + "; ".join(h["reasons"])) if h["reasons"] else ""
            print(f"- {h['ticker']:<6} {px:>10} [{h['verdict'].upper():5}]{why}")
    print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
