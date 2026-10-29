"""Form 4 cluster-buy scanner (v2, DRAFT — not yet verified live).

Replaces the OpenInsider scrape (form4_scanner.py), which broke twice
2026-10-26/27: first a layout change ("tinytable not found"), then the site
became unreachable from this environment entirely (direct fetch timeouts;
live browser connection resets). Per FORM4_SCANNER_SPEC.md, two breaks
trigger this Finnhub-keyed rewrite.

Data: Finnhub /stock/insider-transactions, per symbol.
  GET https://finnhub.io/api/v1/stock/insider-transactions
      ?symbol=<SYM>&from=<YYYY-MM-DD>&to=<YYYY-MM-DD>&token=<KEY>
  Response: {"symbol": ..., "data": [{name, share, change, filingDate,
  transactionDate, transactionCode, transactionPrice, ...}]}
  Verified against the Finnhub docs page 2026-10-27 (read-only, no live
  call): 'share' is shares held AFTER the transaction, NOT the transacted
  amount — the transacted amount is 'change' (positive = buy, negative =
  sell). Code below therefore sizes every transaction from 'change' and
  skips a row with no 'change' rather than misreading 'share' as size.
  Docs also state a limit of 100 transactions per API call; a 30-day
  window per book name should sit under that, but the live run must
  confirm it (and paginate/split the window if a name ever exceeds it).

Key: read from the FINNHUB_API_KEY environment variable only. Never
hard-code a key in this file, and never print it.

Universe: per-symbol endpoint, so no universe scan exists. Default is the
book's current holdings as of the 2026-10-27 morning session
(CRWD, SMMT, GRAB, SOFI); extend with --symbols or a --symbols-file
(one ticker per line). This is deliberately narrower than v1's
OpenInsider top-100 cluster page — a Finnhub rewrite cannot scan the
whole market on the free tier, so it watches the book plus a watchlist.

Cluster definition (from the spec, unchanged):
  - 2+ distinct insiders with code 'P' (open-market buy) within
    5 trading days, OR a single buy over $1M.
  - Only 'P' rows count as buys; 'M' exercises are skipped; 'S' rows in
    the same window feed the mixed-signal flag only.
  - Lookback: 30 calendar days of transactions, clustered on
    transactionDate (not filingDate).

Output: same dated markdown digest the 9:40 session reads, next to the
x-pulse digests:
    ~/workspace/goals/agentic-account-trading-operation/hidden_files/form4-scan-YYYY-MM-DD.md

Standing rules baked in (unchanged from v1):
  - Insider buying is reported as a signal, never as a price target.
  - Mixed signals (concurrent sales) are flagged explicitly.

Status: DRAFT, written 2026-10-27, NOT run — no Finnhub key is available
in this environment yet. Do not point the Monday discovery-form4-scan
cron at this file until a live run with a real key has been verified
and its output compared against the v1 digest format.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001
    from datetime import timezone as _tz
    ET = _tz(timedelta(hours=-4))

BASE_URL = "https://finnhub.io/api/v1/stock/insider-transactions"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
TIMEOUT_S = 30
FETCH_PAUSE_S = 0.5

DEFAULT_SYMBOLS = ["CRWD", "SMMT", "GRAB", "SOFI"]
LOOKBACK_DAYS = 30
CLUSTER_WINDOW_DAYS = 5
SINGLE_BUY_THRESHOLD = 1_000_000

OUT_DIR = (Path.home() / "workspace/goals/agentic-account-trading-operation"
           / "hidden_files")


def _pick(row: dict, *names):
    for n in names:
        if row.get(n) is not None:
            return row[n]
    return None


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_money(v: float) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:,.0f}"


def fetch_transactions(symbol: str, start: date, end: date, token: str) -> list[dict]:
    params = {"symbol": symbol, "from": start.isoformat(),
              "to": end.isoformat(), "token": token}
    url = f"{BASE_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Finnhub HTTP {e.code} for {symbol}: {body}") from e
    except (URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"Finnhub fetch failed for {symbol}: {e}") from e
    rows = payload.get("data") if isinstance(payload, dict) else None
    if rows is None:
        raise RuntimeError(f"Finnhub returned no 'data' for {symbol}: "
                           f"{str(payload)[:300]}")
    return rows


def normalize(symbol: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split normalized rows into buys (code P) and sales (code S)."""
    buys, sales = [], []
    for r in rows:
        code = str(_pick(r, "transactionCode", "transaction_code") or "").strip()
        if not code:
            continue
        price = _num(_pick(r, "transactionPrice", "transaction_price"))
        # 'change' is the ONLY transacted-share count. 'share' is shares
        # held after the transaction and must never be used as size.
        change = _pick(r, "change")
        if change is None:
            continue  # size unknown — never guess it from 'share'
        shares = abs(_num(change))
        rec = {
            "symbol": symbol,
            "name": str(_pick(r, "name", "personName") or "unknown"),
            "trade_date": _date(_pick(r, "transactionDate", "transaction_date")),
            "filing_date": _date(_pick(r, "filingDate", "filing_date")),
            "code": code,
            "price": price,
            "shares": shares,
            "value": price * shares,
        }
        if code.startswith("P"):
            buys.append(rec)
        elif code.startswith("S"):
            sales.append(rec)
        # 'M' exercises, 'A' awards, 'F' tax, 'G' gifts: ignored per spec.
    return buys, sales


def find_clusters(buys: list[dict]) -> list[dict]:
    """Group buys into clusters per the spec definition."""
    clusters = []
    buys = sorted(buys, key=lambda b: (b["trade_date"] or date.min, b["name"]))
    used = set()
    for i, b in enumerate(buys):
        if id(b) in used or b["trade_date"] is None:
            continue
        window = [x for x in buys
                  if x["trade_date"] is not None
                  and b["trade_date"] <= x["trade_date"]
                  <= b["trade_date"] + timedelta(days=CLUSTER_WINDOW_DAYS)]
        insiders = {x["name"] for x in window}
        total = sum(x["value"] for x in window)
        if len(insiders) >= 2 or total >= SINGLE_BUY_THRESHOLD:
            clusters.append({"buys": window, "insiders": insiders, "total": total})
            for x in window:
                used.add(id(x))
    clusters.sort(key=lambda c: (c["total"], len(c["insiders"])), reverse=True)
    return clusters


def run(symbols: list[str], out_dir: Path | None = None,
        token: str | None = None) -> Path:
    token = token or os.environ.get("FINNHUB_API_KEY")
    if not token:
        raise SystemExit("FINNHUB_API_KEY is not set — a free key from "
                         "finnhub.io is required; it is never stored in code.")
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ET).date()
    end, start = today, today - timedelta(days=LOOKBACK_DAYS)
    path = out_dir / f"form4-scan-{today.isoformat()}.md"
    stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    parts = [f"# Form 4 cluster buys — {today.isoformat()}", "",
             f"_Scanned Finnhub insider transactions {stamp}; "
             f"universe: {', '.join(symbols)}; "
             f"cluster = 2+ insiders buying within 5 days or a single buy "
             f"over $1M. Purchases only — exercises excluded; sales flagged "
             f"as mixed signals._", ""]
    any_cluster = False
    for sym in symbols:
        try:
            rows = fetch_transactions(sym, start, end, token)
        except Exception as e:  # noqa: BLE001 — keep the other symbols, note the gap
            parts += [f"## {sym}", f"- _Fetch failed: {e}_", ""]
            continue
        buys, sales = normalize(sym, rows)
        clusters = find_clusters(buys)
        if not clusters:
            parts += [f"## {sym}", "- No cluster buys in the last "
                      f"{LOOKBACK_DAYS} days.", ""]
            continue
        any_cluster = True
        for c in clusters:
            dates = sorted({str(b["trade_date"]) for b in c["buys"]})
            parts += [f"## {sym} — {len(c['insiders'])}-insider cluster, "
                      f"**{fmt_money(c['total'])}**",
                      f"- Traded {dates[0]} to {dates[-1]}"]
            for b in sorted(c["buys"], key=lambda x: -x["value"]):
                parts.append(f"  - {b['name']}: {b['shares']:,.0f} sh @ "
                             f"${b['price']:,.2f} = {fmt_money(b['value'])} "
                             f"(filed {b['filing_date']})")
            window_sales = [s for s in sales
                            if s["trade_date"] is not None
                            and any(b["trade_date"] is not None
                                    and abs((s["trade_date"] - b["trade_date"]).days)
                                    <= CLUSTER_WINDOW_DAYS for b in c["buys"])]
            if window_sales:
                tot = sum(s["value"] for s in window_sales)
                names = ", ".join(sorted({s['name'] for s in window_sales})[:4])
                parts.append(f"- ⚠️ Mixed signal: {len(window_sales)} insider "
                             f"sale(s) ({names}) totaling {fmt_money(tot)} "
                             f"in the same window")
            else:
                parts.append("- Mixed signal: none seen in the window")
            parts += ["- Why it might matter: insider conviction signal; "
                      "weigh against the thesis, not a price target.", ""]
        time.sleep(FETCH_PAUSE_S)
    if not any_cluster:
        parts += ["_No purchase clusters found in this universe today._"]
    path.write_text("\n".join(parts))
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="+", default=None,
                    help="Tickers to scan (default: CRWD SMMT GRAB SOFI)")
    ap.add_argument("--symbols-file", default=None,
                    help="File with one ticker per line; overrides --symbols")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)
    symbols = list(DEFAULT_SYMBOLS)
    if args.symbols_file:
        symbols = [ln.strip().upper() for ln in Path(args.symbols_file).read_text().splitlines()
                   if ln.strip() and not ln.strip().startswith("#")]
    elif args.symbols:
        symbols = [s.upper() for s in args.symbols]
    p = run(symbols, Path(args.out_dir) if args.out_dir else None)
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
