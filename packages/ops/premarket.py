#!/usr/bin/env python3
"""Premarket check on queued names (rule 2026-11-24 machinery).

Runs 8:00 AM ET weekdays, before the 9:40 session. Checks overnight moves
on idea-inbox PENDING names + pending theses (armed and draft) and writes a
brief note the session can read — ONLY if something moved. Silent otherwise.

Flags a name when, vs its previous close:
  - premarket move >= 5% either way, OR
  - (armed trigger only) premarket price is outside [washout_low, max_price]
    — the trigger is dead or un-fireable before the open.

The script does prices only. News triage is the cron worker's job, only for
flagged names (browser.search). The script never places orders.

Usage:
  premarket.py [--dry-run] [--test-quotes PATH]
  --dry-run prints the note it would write, writes nothing.
  --test-quotes loads {SYM: {"premarket": px, "prev_close": px}} instead of
  the live MCP fetch (verification only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date as date_cls
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triggers as trigger_mod  # noqa: E402
from checkin import _refresh_token  # noqa: E402

MCP_PY = str(Path.home() / "workspace/robinhood-mcp/.venv/bin/python")
MCP_TOOL = str(Path.home() / "workspace/robinhood-mcp/mcp_tool.py")
INBOX = (Path.home() / "workspace/goals/agentic-account-trading-operation"
         / "hidden_files/idea-inbox.md")
OUT_DIR = (Path.home() / "workspace/goals/agentic-account-trading-operation"
           / "hidden_files")

MOVE_PCT = 5.0  # flag an overnight move at or beyond this


def inbox_pending() -> list[str]:
    """Tickers in the idea inbox whose entry has no PROCESSED status."""
    if not INBOX.is_file():
        return []
    text = INBOX.read_text()
    out = []
    for m in re.finditer(r"^## ([A-Z]{1,5})\b", text, re.M):
        section = text[m.start():]
        nxt = re.search(r"^## ", section[10:], re.M)
        body = section[:10 + nxt.start()] if nxt else section
        if "PROCESSED" not in body:
            out.append(m.group(1))
    return out


def queued_names() -> dict[str, dict]:
    """{ticker: {pending: raw-or-None}} for inbox PENDING + pending theses."""
    names: dict[str, dict] = {}
    for t in inbox_pending():
        names[t] = {"pending": None}
    pendings, _ = trigger_mod.load_pending()
    for raw in pendings:
        if raw.get("status") in ("armed", "draft"):
            names[raw["ticker"]] = {"pending": raw}
    return names


def fetch_premarket(tickers: list[str]) -> dict[str, dict]:
    """Live quotes via Robinhood MCP, preferring the premarket print.

    Returns {symbol: {premarket, prev_close}}; premarket is None when the
    name has no non-regular-hours trade (e.g. no premarket session yet).
    """
    env = dict(os.environ, NO_PROXY="", no_proxy="")
    for attempt in range(2):
        try:
            out = subprocess.run(
                [MCP_PY, MCP_TOOL, "get_equity_quotes",
                 json.dumps({"symbols": tickers})],
                capture_output=True, text=True, timeout=60, env=env)
            if "JWT verification failed" in out.stdout and attempt == 0:
                if _refresh_token():
                    continue
                return {}
            data = json.loads(out.stdout).get("data", {}).get("results", [])
            quotes = {}
            for r in data:
                q = r.get("quote", {})
                sym = q.get("symbol", "")
                pm = q.get("last_non_reg_trade_price")
                prev = q.get("previous_close")
                if sym and prev:
                    quotes[sym] = {
                        "premarket": float(pm) if pm else None,
                        "prev_close": float(prev),
                    }
            return quotes
        except Exception as e:  # noqa: BLE001
            if attempt == 0 and _refresh_token():
                continue
            print(f"(premarket fetch failed: {e})", file=sys.stderr)
            return {}
    return {}


def evaluate(names: dict[str, dict],
             quotes: dict[str, dict]) -> list[dict]:
    """Flagged names with reasons. Empty list = silent, nothing to write."""
    flags = []
    for sym, info in sorted(names.items()):
        q = quotes.get(sym)
        if not q:
            continue
        pm, prev = q["premarket"], q["prev_close"]
        if pm is None or not prev:
            continue  # no premarket print — nothing moved overnight
        move = (pm / prev - 1) * 100
        reasons = []
        if abs(move) >= MOVE_PCT:
            reasons.append(f"premarket {move:+.1f}% vs prev close "
                           f"${prev:.2f} -> ${pm:.2f}")
        raw = info["pending"]
        if raw and raw.get("status") == "armed":
            entry = raw.get("entry") or {}
            try:
                wl = float(entry["washout_low"])
                mx = float(entry["max_price"])
                if pm > mx:
                    reasons.append(f"premarket ${pm:.2f} above max price "
                                   f"${mx:.2f} — trigger un-fireable today")
                elif pm < wl:
                    reasons.append(f"premarket ${pm:.2f} below washout low "
                                   f"${wl:.2f} — stabilization broken")
            except (KeyError, TypeError, ValueError):
                pass
        if reasons:
            flags.append({"symbol": sym, "premarket": pm,
                          "prev_close": prev, "move_pct": round(move, 2),
                          "reasons": reasons})
    return flags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-quotes", default=None)
    args = ap.parse_args()

    names = queued_names()
    if args.test_quotes:
        raw = json.loads(Path(args.test_quotes).read_text())
        quotes = {s: {"premarket": v.get("premarket"),
                      "prev_close": v.get("prev_close")}
                  for s, v in raw.items()}
    else:
        quotes = fetch_premarket(sorted(names)) if names else {}

    flags = evaluate(names, quotes)
    today = date_cls.today().isoformat()
    summary = {"date": today, "checked": sorted(names),
               "flags": flags}
    print(json.dumps(summary, indent=1))
    if not flags:
        return 0
    lines = [f"# Premarket — {today}", "",
             "Overnight moves on queued names (idea inbox PENDING + pending "
             "theses). The 9:40 session owns the decision; this is the read.",
             ""]
    for f in flags:
        lines.append(f"- **{f['symbol']}** ${f['premarket']:.2f} "
                     f"({f['move_pct']:+.1f}% vs ${f['prev_close']:.2f}): "
                     + "; ".join(f["reasons"]))
    note = "\n".join(lines) + "\n"
    if args.dry_run:
        print("--- note that would be written ---")
        print(note)
        return 0
    out = OUT_DIR / f"premarket-{today}.md"
    out.write_text(note)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
