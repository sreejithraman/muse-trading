"""Form 4 cluster-buy scanner (v1): daily pre-market insider-cluster digest.

Data: openinsider.com "latest cluster buys" page + per-ticker insider pages.
No API key needed (spec's option 2). Verified reachable 2026-10-07.

Cluster definition follows OpenInsider's own clustering (their "Ins" count);
we rank clusters by total $ value and insider count, then pull per-insider
detail (name, title, $ size, SEC filing link) from the ticker page and flag
mixed signals (insider sales in the same window).

Output: dated markdown digest the 9:40 morning session reads, next to the
x_pulse digests:
    ~/workspace/goals/agentic-account-trading-operation/hidden_files/form4-scan-YYYY-MM-DD.md

Standing rules baked in:
- Skip option exercises / planned-sale codes (we only take 'P - Purchase'
  rows; 'S - Sale' rows only feed the mixed-signal flag).
- Insider buying is reported as a signal, never as a price target.

Fragility note (per spec): OpenInsider is plain HTML; if the page layout
changes the parser degrades to an error digest, not a crash. If it breaks
twice, revisit the Finnhub-keyed design in FORM4_SCANNER_SPEC.md.
"""

from __future__ import annotations

import html
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 — fall back to fixed EDT offset
    from datetime import timezone as _tz
    ET = _tz(timedelta(hours=-4))

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
BASES = ["https://openinsider.com", "http://openinsider.com"]
CLUSTER_PATH = "/latest-cluster-buys"
TOP_N = 12
LOOKBACK_DAYS = 7
FETCH_PAUSE_S = 0.5
TIMEOUT_S = 30

OUT_DIR = (Path.home() / "workspace/goals/agentic-account-trading-operation"
           / "hidden_files")


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get(path: str) -> str:
    last: Exception | None = None
    for base in BASES:
        try:
            return fetch(base + path)
        except (URLError, HTTPError, TimeoutError, OSError) as e:
            last = e
    raise RuntimeError(f"fetch failed for {path}: {last}")


def cell_text(cell: str) -> str:
    # Drop tooltip JS before stripping tags so its text doesn't leak in.
    cell = re.sub(r'onmouseover=".*?"', "", cell)
    cell = re.sub(r'onmouseout=".*?"', "", cell)
    text = re.sub(r"<[^>]+>", "", cell)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def anchor_text(cell: str) -> str:
    m = re.search(r">([A-Z][A-Z0-9.\-]{1,10})</a>", cell)
    return m.group(1) if m else cell_text(cell)


def parse_table(page: str) -> tuple[list[str], list[list[str]], list[list[str]]]:
    """Return (headers, raw_cells_rows, text_rows) for the tinytable."""
    m = re.search(r'<table[^>]*class="tinytable"[^>]*>(.*?)</table>', page, re.S)
    if not m:
        raise RuntimeError("tinytable not found — page layout changed?")
    tbl = m.group(1)
    headers = [cell_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", tbl, re.S)]
    raw_rows, text_rows = [], []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if not cells:
            continue
        raw_rows.append(cells)
        text_rows.append([cell_text(c) for c in cells])
    return headers, raw_rows, text_rows


def money(s: str) -> int:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else 0


def fmt_money(v: int) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v}"


def d(s: str):
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def sec_link(cells: list[str]) -> str:
    for c in cells:
        m = re.search(r'href="(https?://www\.sec\.gov[^"]+)"', c)
        if m:
            return m.group(1)
    return ""


def scan_clusters() -> list[dict]:
    page = get(CLUSTER_PATH)
    _headers, raw_rows, text_rows = parse_table(page)
    clusters = []
    for raw, t in zip(raw_rows, text_rows):
        if len(t) < 13:
            continue
        if not t[7].startswith("P"):  # purchases only; exercises/sales excluded
            continue
        try:
            insiders = int(t[6])
        except ValueError:
            insiders = 1
        clusters.append({
            "ticker": anchor_text(raw[3]),
            "company": t[4],
            "industry": t[5],
            "insiders": insiders,
            "price": t[8],
            "qty": t[9],
            "value": money(t[12]),
            "value_s": t[12],
            "trade_date": t[2],
            "filing_date": t[1],
        })
    clusters.sort(key=lambda c: (c["value"], c["insiders"]), reverse=True)
    return clusters[:TOP_N]


def ticker_detail(ticker: str, since: date) -> dict:
    """Per-insider buys + any same-window sales for one ticker."""
    page = get(f"/{ticker}")
    _headers, raw_rows, text_rows = parse_table(page)
    buys, sales = [], []
    for raw, t in zip(raw_rows, text_rows):
        if len(t) < 12:
            continue
        fdate = d(t[1])
        if fdate is None or fdate < since:
            continue
        code = t[6]
        if code.startswith("P"):
            buys.append({
                "name": anchor_text(raw[4]),
                "title": t[5],
                "price": t[7],
                "qty": t[8],
                "value": money(t[11]),
                "value_s": t[11],
                "trade_date": t[2],
                "sec": sec_link(raw),
            })
        elif code.startswith("S"):
            sales.append({"name": anchor_text(raw[4]), "value": money(t[11]),
                          "value_s": t[11]})
        # 'M' exercises and anything else: ignored per standing rules
    buys.sort(key=lambda b: b["value"], reverse=True)
    return {"buys": buys, "sales": sales}


def why_it_matters(c: dict, titles: list[str]) -> str:
    who = ", ".join(titles[:3]) if titles else "insiders"
    return (f"{c['insiders']}-insider cluster ({who}) bought {fmt_money(c['value'])} "
            f"of {c['company']} [{c['industry']}] — insider conviction signal; "
            f"weigh against the thesis, not a price target.")


def run(out_dir: Path | str | None = None) -> Path:
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ET).date().isoformat()
    path = out_dir / f"form4-scan-{today}.md"
    stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    parts = [f"# Form 4 cluster buys — {today}", "",
             f"_Scanned openinsider.com latest cluster buys {stamp}; "
             f"top {TOP_N} purchase clusters by $ value. "
             "Purchases only — exercises excluded; sales flagged as mixed signals._",
             ""]
    try:
        clusters = scan_clusters()
    except Exception as e:  # noqa: BLE001 — a broken scrape must not kill the session read
        parts += [f"_Scan failed: {e}_", "",
                  "The 9:40 session should fall back to the manual Form 4 check."]
        path.write_text("\n".join(parts))
        raise

    if not clusters:
        parts += ["_No purchase clusters found today._"]
        path.write_text("\n".join(parts))
        return path

    since = datetime.now(ET).date() - timedelta(days=LOOKBACK_DAYS)
    for i, c in enumerate(clusters, 1):
        parts += [f"## {i}. {c['ticker']} — {c['company']}",
                  f"_{c['industry']}_", "",
                  f"- Cluster: **{c['insiders']} insiders**, "
                  f"**{fmt_money(c['value'])}** total "
                  f"(@ {c['price']}, {c['qty']} sh)",
                  f"- Traded {c['trade_date']} · filed {c['filing_date'][:10]}"]
        try:
            detail = ticker_detail(c["ticker"], since)
            time.sleep(FETCH_PAUSE_S)
        except Exception as e:  # noqa: BLE001 — keep the cluster row, note the gap
            parts += [f"- _Per-insider detail unavailable: {e}_", ""]
            continue
        if detail["buys"]:
            parts.append("- Buys:")
            for b in detail["buys"][:6]:
                link = f" ([SEC filing]({b['sec']}))" if b["sec"] else ""
                parts.append(f"  - {b['name']} ({b['title']}): "
                             f"{b['qty']} sh @ {b['price']} = {b['value_s']}{link}")
        if detail["sales"]:
            tot = sum(s["value"] for s in detail["sales"])
            names = ", ".join(s["name"] for s in detail["sales"][:4])
            parts.append(f"- ⚠️ Mixed signal: {len(detail['sales'])} insider sale(s) "
                         f"({names}) totaling {fmt_money(tot)} in the same window")
        else:
            parts.append("- Mixed signal: none seen in the last 7 days")
        titles = [b["title"] for b in detail["buys"]]
        parts += [f"- Why it might matter: {why_it_matters(c, titles)}", ""]
    path.write_text("\n".join(parts))
    return path


if __name__ == "__main__":
    p = run()
    print(f"wrote {p}")
