"""Paper book scorer: track paper ideas vs QQQ from their flag date.

The farm team for a possible future second sleeve. No capital changes hands;
this builds the evidence record a real allocation decision would need.
Ledger: packages/paper/ledger.yaml (add ticker + flagged date + thesis;
reference prices fill in automatically on first score).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data"))
import bars  # noqa: E402  (flat import: packages/data uses sibling imports)

LEDGER = Path(__file__).with_name("ledger.yaml")


def _close_on_or_before(symbol: str, date_iso: str) -> tuple[float | None, str | None]:
    """Last daily close on/before date_iso (for reference prices)."""
    for b in reversed(bars.fetch_daily(symbol, range_="3mo")):
        if b["date"] <= date_iso:
            return b["close"], b["date"]
    return None, None


def _ensure_refs(entry: dict) -> bool:
    """Fill missing ref_price/ref_qqq from closes on/before the flag date."""
    if entry.get("ref_price") and entry.get("ref_qqq"):
        return False
    px, pxd = _close_on_or_before(entry["ticker"], entry["flagged"])
    qx, qxd = _close_on_or_before("QQQ", entry["flagged"])
    if px and qx:
        entry["ref_price"], entry["ref_qqq"] = round(px, 2), round(qx, 2)
        entry["ref_date"] = pxd if pxd == qxd else f"{pxd}/{qxd}"
        return True
    return False


def score() -> list[dict]:
    raw = yaml.safe_load(LEDGER.read_text()) or {}
    entries = raw.get("entries", [])
    dirty = False
    for e in entries:
        if e.get("status") == "tracking":
            dirty |= _ensure_refs(e)
    if dirty:
        LEDGER.write_text(yaml.safe_dump(raw, sort_keys=False))
    qqq_now = bars.last_close("QQQ")
    rows = []
    for e in entries:
        if e.get("status") != "tracking" or not e.get("ref_price"):
            continue
        px = bars.last_close(e["ticker"])
        if not px or not qqq_now:
            continue
        r = (px / e["ref_price"] - 1) * 100
        rq = (qqq_now / e["ref_qqq"] - 1) * 100
        rows.append({
            "ticker": e["ticker"],
            "flagged": e["flagged"],
            "idea": round(r, 1),
            "qqq": round(rq, 1),
            "excess": round(r - rq, 1),
        })
    return rows


def main() -> None:
    rows = score()
    if not rows:
        print("paper book: no tracking entries")
        return
    print(f"{'ticker':<8}{'flagged':<12}{'idea %':>8}{'QQQ %':>8}{'excess %':>9}")
    for r in rows:
        print(f"{r['ticker']:<8}{r['flagged']:<12}{r['idea']:>8.1f}"
              f"{r['qqq']:>8.1f}{r['excess']:>9.1f}")


if __name__ == "__main__":
    main()
