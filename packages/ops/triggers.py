#!/usr/bin/env python3
"""Pre-registered entry triggers (rule 2026-11-24).

A pending thesis in packages/thesis/pending/<TICKER>.yaml may carry an entry
trigger. When it fires during market hours, the entry executes without a
9:40 session deliberation — the judgment was registered before the event.

STABILIZATION (v1) — the only trigger condition. Evaluated by the
circuit-watch at a 15-min poll at or after 10:00 AM ET; ALL must hold:
  1. not a gap day: today's open within +/-3% of prior close
  2. no retest: today's intraday low so far > washout low
  3. reclaimed: current price >= reference close (washout-day close)
  4. hard cap: current price <= max_price (never chase above it)
Fire once per symbol per day (dedup lives in the hook's seen-state).
A trigger that has not fired by its expiry dies — the emitter simply stops
emitting it. No silent extension.

This module is pure logic (no orders, no network): the hook imports it,
the check-in emits from it, and the dry-run tests exercise it directly.
Only `armed` triggers with expiry >= today are ever emitted.
"""
from __future__ import annotations

import sys
from datetime import date as date_cls
from pathlib import Path

import yaml

PENDING_DIR = Path(__file__).resolve().parent.parent / "thesis" / "pending"

GAP_PCT = 3.0       # today's open must be within +/-3% of prior close
EARLIEST_HHMM = 1000  # no trigger fires in the first 30 min of the session


def load_pending() -> tuple[list[dict], list[str]]:
    """All pending files + warnings for malformed ones (never crash the emitter).

    Returns (pendings, warnings). Each pending is the raw YAML dict.
    """
    pendings, warnings = [], []
    if not PENDING_DIR.is_dir():
        return pendings, warnings
    for p in sorted(PENDING_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{p.name}: unparsable ({e}) — skipped")
            continue
        if not isinstance(raw, dict) or not raw.get("ticker"):
            warnings.append(f"{p.name}: no ticker — skipped")
            continue
        raw["_file"] = p.name
        pendings.append(raw)
    return pendings, warnings


def armed_triggers(today: str | None = None) -> tuple[list[dict], list[str]]:
    """Triggers live right now: status == 'armed' and expiry >= today.

    Each entry is the watchlist shape the hook evaluates:
    {symbol, reference_close, washout_low, max_price, red_line, expires}.
    """
    today = today or date_cls.today().isoformat()
    pendings, warnings = load_pending()
    out = []
    for raw in pendings:
        if raw.get("status") != "armed":
            continue
        exp = str(raw.get("expires") or "")
        if exp and exp < today:
            continue  # died at expiry — no silent extension
        entry = raw.get("entry") or {}
        try:
            out.append({
                "symbol": raw["ticker"],
                "reference_close": float(entry["reference_close"]),
                "washout_low": float(entry["washout_low"]),
                "max_price": float(entry["max_price"]),
                "red_line": float(entry["red_line"]),
                "expires": exp,
            })
        except (KeyError, TypeError, ValueError):
            warnings.append(
                f"{raw.get('_file', raw['ticker'])}: armed but entry levels "
                "incomplete — skipped (arm it with full levels or cut it)")
    return out, warnings


def evaluate_trigger(trig: dict, price: float, today_open: float | None,
                     today_low: float | None, prev_close: float | None,
                     hhmm_et: int) -> tuple[bool, str]:
    """STABILIZATION (v1). Returns (fired, reason)."""
    if hhmm_et < EARLIEST_HHMM:
        return False, "before 10:00 ET — open noise, not stabilization"
    if prev_close is None or today_open is None or today_low is None:
        return False, "missing open/low/prev-close — cannot judge, no fire"
    if abs(today_open / prev_close - 1) * 100 > GAP_PCT:
        return False, (f"gap day: open ${today_open:.2f} vs prev close "
                       f"${prev_close:.2f} — no chasing gaps")
    if today_low <= trig["washout_low"]:
        return False, (f"retested washout low: today low ${today_low:.2f} "
                       f"<= ${trig['washout_low']:.2f}")
    if price < trig["reference_close"]:
        return False, (f"below reference close: ${price:.2f} < "
                       f"${trig['reference_close']:.2f}")
    if price > trig["max_price"]:
        return False, (f"above max price: ${price:.2f} > "
                       f"${trig['max_price']:.2f} — hard cap, no chase")
    return True, (f"STABILIZED: ${price:.2f} reclaimed ref close "
                  f"${trig['reference_close']:.2f}, held above washout low "
                  f"${trig['washout_low']:.2f}, under max "
                  f"${trig['max_price']:.2f}")


def main() -> int:
    """Standalone: print the armed triggers that would emit right now."""
    import json
    trigs, warns = armed_triggers()
    for w in warns:
        print(f"WARNING: {w}", file=sys.stderr)
    print(json.dumps({"date": date_cls.today().isoformat(),
                      "armed": trigs}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
