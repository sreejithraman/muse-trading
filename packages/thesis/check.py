#!/usr/bin/env python3
"""Thesis status board: every thesis checked against live prices.

Loads all theses from theses/*.yaml, pulls live quotes via the Robinhood
MCP helper, and prints one line per holding: status, price vs blended,
distance to each price red line, and the next key date. Flags anything
within 5% of a red-line price.

Usage:  python3 check.py            (uses ~/workspace/robinhood-mcp helper)
        python3 check.py --offline  (theses only, no live prices)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import load_all  # noqa: E402

MCP_PY = str(Path.home() / "workspace/robinhood-mcp/.venv/bin/python")
MCP_TOOL = str(Path.home() / "workspace/robinhood-mcp/mcp_tool.py")
WARN_PCT = 5.0  # flag red lines within this % of current price


def fetch_quotes(tickers: list[str]) -> dict[str, float]:
    """Live last-trade prices via Robinhood MCP. Returns {} on any failure."""
    env = dict(os.environ, NO_PROXY="", no_proxy="")
    try:
        out = subprocess.run(
            [MCP_PY, MCP_TOOL, "get_equity_quotes",
             json.dumps({"symbols": tickers})],
            capture_output=True, text=True, timeout=60, env=env,
        )
        data = json.loads(out.stdout).get("data", {}).get("results", [])
        quotes = {}
        for r in data:
            q = r.get("quote", {})
            px = q.get("last_trade_price") or q.get("last_non_reg_trade_price")
            if px:
                quotes[q.get("symbol", "")] = float(px)
        return quotes
    except Exception as e:  # noqa: BLE001 — offline mode must never crash
        print(f"(quote fetch failed: {e}; running offline)", file=sys.stderr)
        return {}


def main() -> int:
    offline = "--offline" in sys.argv
    theses = load_all()
    tickers = [t.ticker for t in theses]
    quotes = {} if offline else fetch_quotes(tickers)
    today = date.today().isoformat()

    print(f"{'TICKER':<7}{'STATUS':<10}{'PRICE':>9}{'vsCOST':>8}"
          f"{'STOP-DIST':>10}{'NEXT KEY DATE':>22}  FLAGS")
    print("-" * 92)
    for t in theses:
        px = quotes.get(t.ticker)
        pos = t.position
        blended = pos.blended_cost if pos else None
        stop = pos.stop if pos else None

        vs_cost = f"{(px / blended - 1) * 100:+.1f}%" if px and blended else "—"
        stop_dist = f"{(px / stop - 1) * 100:+.1f}%" if px and stop else "—"
        px_s = f"{px:.2f}" if px else "(offline)"

        # next upcoming key date
        upcoming = sorted((k for k in t.key_dates if k.date >= today),
                          key=lambda k: k.date)
        nxt = f"{upcoming[0].date} {upcoming[0].event[:28]}" if upcoming else "—"

        # red-line proximity flags
        flags = []
        if px:
            for rl in t.red_lines:
                if rl.price_level:
                    dist = (px / rl.price_level - 1) * 100
                    if 0 <= dist <= WARN_PCT:
                        flags.append(f"⚠ {dist:.1f}% above ${rl.price_level:g}")
                    elif dist < 0:
                        flags.append(f"✖ BELOW ${rl.price_level:g}: {rl.action[:40]}")
        if t.status != "INTACT":
            flags.append(f"[{t.status}]")

        print(f"{t.ticker:<7}{t.status:<10}{px_s:>9}{vs_cost:>8}"
              f"{stop_dist:>10}{nxt:>22}  {'; '.join(flags)}")
    print("-" * 92)
    print(f"{len(theses)} theses · {today}"
          f"{' · OFFLINE (no live prices)' if offline or not quotes else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
