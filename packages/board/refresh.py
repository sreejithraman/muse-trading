#!/usr/bin/env python3
"""Deterministic board refresh for Mu$e's Book — one process, no agent.

Standing rule (2026-11-11): code by default, agent only where a judgment
is named. The old refresh spawned a background agent that fetched prices,
ran the generator, translated the output, and saved — one reasoning step
at a time, 2–4 minutes for a job with no judgment in it. This script does
the whole pipeline mechanically in seconds:

  1. Fetch live quotes + account state from the Robinhood MCP
     (equity quotes for every open ticker + QQQ/SPY, portfolio total/cash,
     equity positions, and the open option's mark via option quotes).
  2. Read reconciliation figures from the performance ledger
     (running peak, cumulative realized P&L, per-exit realized).
     An exit made today is not in the ledger yet — scoring writes the
     Running state only at the 16:10 close — so a same-day exit is
     reconciled against the broker's own realized P&L for today
     (pending exits): the board refreshes the same day the exit
     happens instead of failing until the close. An exit dated before
     today with no ledger figure still fails loudly — that is stale
     data, not timing.
  3. Maintain packages/board/series.json (morning/midday leave it alone;
     the close refresh upserts today's point from the ledger's scored
     session row when one exists).
  4. Run packages/board/generate.py over the thesis files.
  5. Translate the generator output into the Book's board schema.
  6. Sanity-check the result. On ANY failed check or missing quote:
     exit non-zero with a plain error and DO NOT emit a board — the
     caller keeps the last good board and surfaces the failure, and the
     next session/agent investigates. That failure path is where the
     judgment lives now, not inside the refresh.

Cadence (2026-11-11): the page refresh is purely mechanical, so it runs
every 15 minutes during market hours — decoupled from the judgment cycle
(morning session 9:40, midday check 12:30, close review 15:50, scoring
16:10), which keeps its own cadence and no longer drives this script.
The script is built for that frequency: idempotent (the close series
point upserts by date, so it lands exactly once per day, on the first
close-phase run that finds the ledger's scored row), cheap (~seconds of
read-only MCP calls), single-flight (a lockfile turns an overlapping
invocation into a plain "already running" result), and schedule-gated
(--scheduled runs no-op outside 9:30–16:30 ET on weekdays; the window
runs 30 minutes past the 16:00 close so the day's series point lands
after scoring). The manual Refresh button passes no --scheduled flag
and works anytime.

Usage:
    python3 packages/board/refresh.py \
        --previous-board /path/to/previous-board.json \
        --out /path/to/result.json [--scheduled]

Result JSON: {"ok": true, "elapsedMs": <int>, "board": {...}},
             {"ok": true, "skipped": true, "reason": "..."} for a
             scheduled run outside the window, or
             {"ok": false, "elapsedMs": <int>, "error": "<plain text>"}.
The previous board is the artifact's currently saved board (same schema
as the output); it feeds the account-value sanity band, watch-item
carryover, and series reconstruction. It is optional — without it the
band/carryover checks are skipped, never guessed.

Read-only against the broker: this script never places, modifies, or
cancels an order.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # ~/workspace/trading-tools
LEDGER = (
    Path.home()
    / "workspace/goals/agentic-account-trading-operation/files/performance-ledger.md"
)
SERIES_PATH = HERE / "series.json"
GENERATOR = HERE / "generate.py"

MCP_PY = str(Path.home() / "workspace/robinhood-mcp/.venv/bin/python")
MCP_TOOL = str(Path.home() / "workspace/robinhood-mcp/mcp_tool.py")
RH_DIR = Path.home() / "workspace/robinhood-mcp"

ET = ZoneInfo("America/New_York")

# Baselines from the performance ledger (2026-09-18 inception).
ACCT_BASELINE = 1954.75  # deposit-adjusted ($454.75 + $1,500 on 2026-10-06)
QQQ_BASELINE = 716.92  # QQQ 2026-09-18 baseline per ledger Running state
SPY_BASELINE = 761.69  # SPY 2026-09-18 close

ACCOUNT_BAND = 0.25  # new total must be within ±25% of the last saved one


class RefreshError(Exception):
    """A check failed or a source was unavailable: abort, do not save."""


def _agentic_account() -> str:
    """Robinhood account number — never hardcoded in the repo.

    Env var ROBINHOOD_ACCOUNT_NUMBER first, else the private file
    ~/workspace/robinhood-mcp/.account_number (outside both repos,
    never synced). Fails loudly if neither exists.
    """
    acct = os.environ.get("ROBINHOOD_ACCOUNT_NUMBER", "").strip()
    if acct:
        return acct
    acct_file = Path.home() / "workspace/robinhood-mcp/.account_number"
    if acct_file.exists():
        return acct_file.read_text().strip()
    raise RefreshError(
        "ROBINHOOD_ACCOUNT_NUMBER is not set and "
        "~/workspace/robinhood-mcp/.account_number is missing."
    )


AGENTIC_ACCOUNT = _agentic_account()


# ---------------------------------------------------------------- MCP ----

def _refresh_token() -> bool:
    """One-shot OAuth refresh, same recovery checkin.py uses."""
    try:
        from urllib.parse import urlencode
        from urllib import request as rq

        state = json.loads((RH_DIR / ".oauth_state.json").read_text())
        tokp = RH_DIR / ".tokens.json"
        tokens = json.loads(tokp.read_text())
        data = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": state["client_id"],
            }
        ).encode()
        req = rq.Request(state["token_endpoint"], data=data, method="POST")
        with rq.urlopen(req, timeout=20) as r:
            new = json.loads(r.read().decode())
        tokens["access_token"] = new.get("access_token", tokens["access_token"])
        if new.get("refresh_token"):
            tokens["refresh_token"] = new["refresh_token"]
        tokp.write_text(json.dumps(tokens))
        os.chmod(tokp, 0o600)
        print("(access token refreshed)", file=sys.stderr)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"(token refresh failed: {e})", file=sys.stderr)
        return False


def mcp_call(tool: str, args: dict) -> dict:
    """One Robinhood MCP tool call via the repo's mcp_tool.py helper.

    Returns the tool's `data` object. Raises RefreshError on any failure —
    a missing quote must stop the refresh, never be estimated.
    """
    env = dict(os.environ, NO_PROXY="", no_proxy="")
    for attempt in range(2):
        try:
            out = subprocess.run(
                [MCP_PY, MCP_TOOL, tool, json.dumps(args)],
                capture_output=True, text=True, timeout=60, env=env,
            )
        except Exception as e:  # noqa: BLE001
            raise RefreshError(f"Robinhood {tool} could not run: {e}") from e
        if "JWT verification failed" in (out.stdout or "") and attempt == 0:
            if _refresh_token():
                continue
            raise RefreshError("Robinhood login expired and token refresh failed.")
        try:
            payload = json.loads(out.stdout)
        except Exception as e:  # noqa: BLE001
            raise RefreshError(
                f"Robinhood {tool} returned unreadable output."
            ) from e
        if "error" in payload:
            raise RefreshError(f"Robinhood {tool} failed: {payload['error']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RefreshError(f"Robinhood {tool} returned no data.")
        return data
    raise RefreshError(f"Robinhood {tool} failed after a token refresh.")


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """{symbol: {price, prev_close}} from get_equity_quotes.

    prev_close is the official prior-session close (results[].close.price),
    falling back to quote.previous_close. Every symbol must come back with
    a positive, actually-traded price or the refresh aborts.
    """
    data = mcp_call("get_equity_quotes", {"symbols": symbols})
    quotes: dict[str, dict] = {}
    for r in data.get("results", []):
        q = r.get("quote", {})
        sym = q.get("symbol", "")
        px = q.get("last_trade_price") or q.get("last_non_reg_trade_price")
        if not sym or not px:
            continue
        close = (r.get("close") or {}).get("price")
        prev = float(close) if close else (
            float(q["previous_close"]) if q.get("previous_close") else None
        )
        quotes[sym] = {
            "price": float(px),
            "prev_close": prev,
            "has_traded": q.get("has_traded"),
            "state": q.get("state"),
        }
    missing = [s for s in symbols if s not in quotes]
    if missing:
        raise RefreshError(f"No live quote for {', '.join(missing)}.")
    for sym, q in quotes.items():
        if q["price"] <= 0 or q["prev_close"] is None or q["prev_close"] <= 0:
            raise RefreshError(f"Quote for {sym} is empty or stale — aborting.")
        if q["has_traded"] is False or (q["state"] not in (None, "active")):
            raise RefreshError(f"Quote for {sym} has not traded / is not active.")
    return quotes


def fetch_today_realized() -> dict[str, float]:
    """Today's realized P&L per symbol, from the broker's P&L history.

    get_pnl_trade_history returns closed/realizing trades only, so every
    entry is a close with its realized gain. Same source score.py uses
    at the 16:10 close — the two agree by construction.
    """
    today_iso = datetime.now(ET).date().isoformat()
    realized: dict[str, float] = {}
    cursor = ""
    for _ in range(10):
        args: dict = {"account_number": AGENTIC_ACCOUNT}
        if cursor:
            args["next_cursor"] = cursor
        data = mcp_call("get_pnl_trade_history", args)
        for t in data.get("trades", []):
            ts = t.get("timestamp", "")
            try:
                day = datetime.fromisoformat(
                    ts.replace("Z", "+00:00")).astimezone(ET).date().isoformat()
            except ValueError:
                continue
            if day != today_iso:
                continue
            sym = t.get("symbol", "")
            if sym:
                realized[sym] = round(
                    realized.get(sym, 0.0)
                    + float(t.get("realized_gain") or 0), 2)
        cursor = data.get("next_cursor") or ""
        if not cursor:
            break
    return realized


def pending_exits(gen_exits: list, ledger: dict) -> dict[str, float]:
    """Realized figures for exits the ledger has not absorbed yet.

    Scoring writes the ledger's Running state only at the 16:10 close,
    so an exit made earlier today is in the thesis files (and therefore
    in the generator's exit log) but has no figure in the ledger's
    per-exit breakdown. Those exits reconcile against the broker's
    realized P&L for today instead — the same source scoring will use
    at the close, so the board and the ledger agree once scoring runs.
    An exit dated before today with no ledger figure is not timing:
    fail loudly, as before.
    """
    missing = [
        e for e in gen_exits
        if e.get("ticker") not in ledger["perExit"]
    ]
    if not missing:
        return {}
    today_iso = datetime.now(ET).date().isoformat()
    for e in missing:
        if str(e.get("closed")) != today_iso:
            raise RefreshError(
                f"Ledger has no realized figure for the {e.get('ticker')} "
                "exit — the exit log cannot be reconciled."
            )
    realized = fetch_today_realized()
    pending: dict[str, float] = {}
    for e in missing:
        ticker = e.get("ticker")
        if ticker not in realized:
            raise RefreshError(
                f"Ledger has no realized figure for the {ticker} exit and "
                "no realized trade for it today — the exit log cannot be "
                "reconciled."
            )
        pending[ticker] = realized[ticker]
    return pending



# -------------------------------------------------------------- ledger ----

def _money(s: str) -> float:
    return float(s.replace("$", "").replace(",", ""))


def parse_ledger() -> dict:
    if not LEDGER.exists():
        raise RefreshError("Performance ledger not found — cannot reconcile.")
    text = LEDGER.read_text()

    m = re.search(r"Running peak:\s*\*\*\$([\d,]+\.\d+)\*\*", text)
    if not m:
        raise RefreshError("Ledger Running state has no running peak.")
    peak = float(m.group(1).replace(",", ""))

    m = re.search(r"Cumulative realized P&L:\s*\*\*([+-]?\$[\d,]+\.\d+)\*\*", text)
    if not m:
        raise RefreshError("Ledger Running state has no cumulative realized P&L.")
    realized_cum = _money(m.group(1))

    # Per-exit realized figures, from the Running-state breakdown sentence
    # plus the day-one liquidation in the 2026-09-18 session block. If the
    # ledger's wording changes, these stop matching and the exits-sum
    # check below fails loudly instead of publishing wrong numbers.
    # Search ONLY the Cumulative-realized line: a bare "GRAB -$3.97" or
    # "SMMT $69.65" in a session block is a day mark, not a realized exit,
    # and the new GRAB/SMMT patterns would otherwise match it first.
    patterns = {
        "INTC": r"INTC\s+([+-]?\$[\d,]+\.\d+)",
        "ARWR": r"ARWR\s+([+-]?\$[\d,]+\.\d+)",
        "RKLB": r"RKLB\s+([+-]?\$[\d,]+\.\d+)",
        "MU": r"MU\s+([+-]?\$[\d,]+\.\d+)",
        "CRWD": r"CRWD\s+([+-]?\$[\d,]+\.\d+)",
        "GRAB_CALLS": r"GRAB Nov \$3 calls\s+([+-]?\$[\d,]+\.\d+)",
        "GRAB": r"GRAB\s+([+-]?\$[\d,]+\.\d+)",
        "SMMT": r"SMMT\s+([+-]?\$[\d,]+\.\d+)",
        "SOFI": r"SOFI(?:\s+Jan\s+\d+\s+2028\s+\$15\s+calls?)?\s+([+-]?\$[\d,]+\.\d+)",
    }
    running_line = next(
        (ln for ln in text.splitlines() if "Cumulative realized P&L:" in ln), ""
    )
    per_exit: dict[str, float] = {}
    for key, pat in patterns.items():
        mm = re.search(pat, running_line)
        if mm:
            per_exit[key] = _money(mm.group(1))
    day1 = re.search(
        r"### 2026-09-18.*?Realized P&L:\s*\*\*(-\$[\d,]+\.\d+)\*\*",
        text, re.DOTALL,
    )
    if day1:
        per_exit["INHERITED"] = _money(day1.group(1))

    # Session blocks: date -> cumulative % pair (for the close series).
    sessions: dict[str, dict] = {}
    for block in re.finditer(
        r"### (\d{4}-\d{2}-\d{2}) —[^\n]*\n(.*?)(?=\n### |\Z)", text, re.DOTALL
    ):
        body = block.group(2)
        cum = re.search(
            r"Cumulative: account \*\*(-?[\d.]+)%\*\*.*?QQQ \*\*(-?[\d.]+)%\*\*",
            body, re.DOTALL,
        )
        if cum:
            sessions[block.group(1)] = {
                "acctPct": float(cum.group(1)),
                "qqqPct": float(cum.group(2)),
            }
    return {"peak": peak, "realizedCum": realized_cum,
            "perExit": per_exit, "sessions": sessions}


# ------------------------------------------------------------- helpers ----

def fmt_money(v: float) -> str:
    return f"${v:,.2f}"


def money_in_text(text: str) -> str:
    """Every $ amount in free text at exactly two decimals ($60 -> $60.00);
    shorthand magnitudes like $30M / $2B are left alone."""

    def repl(m: re.Match) -> str:
        return fmt_money(float(m.group(1).replace(",", "")))

    return re.sub(r"\$(\d[\d,]*(?:\.\d+)?)(?![A-Za-z])", repl, text)


def label_date(iso: str, today: date_cls) -> str:
    """'2026-11-14' -> 'Sat Nov 14'. A date outside the current year
    keeps its year — '2027-09-30' -> 'Thu Sep 30 2027' — so a far-out
    event never reads as this year's (or last year's) date."""
    d = date_cls.fromisoformat(iso)
    if d.year == today.year:
        return f"{d:%a %b} {d.day}"
    return f"{d:%a %b} {d.day} {d.year}"


def short_date(iso: str) -> str:
    """'2026-11-14' -> 'Nov 14' (series / exit date labels)."""
    d = date_cls.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def first_sentence(text: str) -> str:
    """The thesis one-liner: first sentence of the generator's `why`,
    cut — not reworded — to one line of at most ~240 characters."""
    flat = " ".join((text or "").split())
    m = re.search(r"^(.*?\.)\s", flat)
    sent = m.group(1) if m else flat
    return sent[:240].strip()


def num_label(v: float) -> str:
    """66.2 -> '66.2', 5.70 -> '5.7', 100.0 -> '100'."""
    return f"{v:f}".rstrip("0").rstrip(".") if "." in f"{v:f}" else f"{v:f}"


# --------------------------------------------------------- translation ----

def translate_positions(gen_positions: list, theses_by_ticker: dict,
                          phase: str, today_iso: str) -> list:
    price_word = "close" if phase == "close" else "last"
    out = []
    for card in gen_positions:
        ticker = card["ticker"]
        status = (card.get("status") or "INTACT").capitalize()
        why = first_sentence(card.get("why") or "")
        if card.get("kind") == "option":
            contracts = int(card.get("contracts") or 0)
            premium_now = card.get("premium_now")
            premium_paid = card.get("premium_paid")
            if premium_now is None or premium_paid is None:
                raise RefreshError(f"No live premium for the {ticker} option.")
            cg = card.get("contract_gauge") or {}
            sg = card.get("stock_gauge") or {}
            total_now = round(premium_now * 100 * contracts, 2)
            total_paid = round(premium_paid * 100 * contracts, 2)
            exit_premium = cg.get("exit_premium")
            stop_total = (
                round(exit_premium * 100 * contracts, 2)
                if exit_premium is not None else None
            )
            tp_premium = cg.get("take_profit_premium")
            tp_total = (
                round(tp_premium * 100 * contracts, 2)
                if tp_premium is not None else None
            )
            expiry = str(card.get("expiry") or "")
            try:
                exp_label = datetime.strptime(expiry, "%Y-%m-%d").strftime("%b %Y")
            except ValueError:
                exp_label = expiry
            # LEAP when expiry is over a year past the as-of date.
            try:
                days_out = (date_cls.fromisoformat(expiry)
                            - date_cls.fromisoformat(today_iso)).days
                kind = "LEAP call" if days_out > 365 else "Call"
            except ValueError:
                kind = "Call"
            thesis = theses_by_ticker.get(ticker)
            tp_qty = (
                thesis.position.take_profit_qty
                if thesis is not None and thesis.position is not None else None
            )
            tp_fraction = 1.0 if tp_qty == "all" else (
                0.5 if tp_qty == "half" else None
            )
            out.append({
                "ticker": ticker,
                "name": card.get("name") or ticker,
                "kind": kind,
                "qtyLabel": (
                    f"{contracts} contract{'s' if contracts != 1 else ''} · "
                    f"{exp_label} {fmt_money(float(card.get('strike') or 0))} call"
                ),
                "price": total_now,
                "priceLabel": f"{fmt_money(total_now)} mark",
                "costBasis": total_paid,
                "pnlPct": card.get("pnl_pct"),
                "statusLabel": status,
                "stopPrice": stop_total,
                "stopLabel": (
                    f"-50% premium line · {fmt_money(stop_total)}"
                    if stop_total is not None else "—"
                ),
                "stopSuspended": False,
                "takeProfit": tp_total,
                "takeProfitLabel": (
                    f"Take-profit {fmt_money(tp_total)} · premium double"
                    if tp_total is not None else None
                ),
                "takeProfitFraction": tp_fraction if tp_total is not None else None,
                "underlyingPrice": sg.get("now"),
                "breakevenPrice": sg.get("breakeven"),
                "thesis": why,
            })
        else:
            sg = card.get("stock_gauge") or {}
            shares = float(card.get("shares") or 0)
            price = float(sg.get("now") or card.get("price") or 0)
            stop = sg.get("exit_line")
            suspended_until = sg.get("exit_suspended_until")
            suspended = bool(
                suspended_until and today_iso <= str(suspended_until)
            )
            status_label = status
            if suspended:
                status_label += f" · line suspended to {short_date(str(suspended_until))}"
            if stop is None:
                stop_label = "—"
            elif suspended:
                stop_label = f"Line {fmt_money(float(stop))} · suspended"
            else:
                stop_label = f"Red line {fmt_money(float(stop))} · close-based"
            tp = sg.get("take_profit")
            tp_qty = sg.get("take_profit_qty")
            tp_label = None
            tp_fraction = None
            if tp is not None:
                tp_label = f"Take-profit {fmt_money(float(tp))}"
                if tp_qty and re.search(r"\d", str(tp_qty)) and "sh" in str(tp_qty):
                    tp_label += f" · {tp_qty} resting"
                    n = float(re.search(r"([\d.]+)", str(tp_qty)).group(1))
                    ratio = n / shares if shares else 0
                    tp_fraction = (
                        0.5 if abs(ratio - 0.5) < 0.03
                        else 1.0 if abs(ratio - 1) < 0.03
                        else round(ratio, 2)
                    )
                elif tp_qty == "half":
                    tp_fraction = 0.5
                elif tp_qty == "all":
                    tp_fraction = 1.0
            out.append({
                "ticker": ticker,
                "name": card.get("name") or ticker,
                "kind": "Shares",
                "qtyLabel": f"{num_label(shares)} sh",
                "price": price,
                "priceLabel": f"{fmt_money(price)} {price_word}",
                "costBasis": card.get("bought_at"),
                "pnlPct": card.get("pnl_pct"),
                "statusLabel": status_label,
                "stopPrice": stop,
                "stopLabel": stop_label,
                "stopSuspended": suspended,
                "takeProfit": tp,
                "takeProfitLabel": tp_label,
                "takeProfitFraction": tp_fraction,
                "underlyingPrice": None,
                "breakevenPrice": None,
                "thesis": why,
            })
    return out


def translate_exits(gen_exits: list, ledger: dict, prev_exits: list,
                    pending: dict | None = None) -> list:
    # Pending same-day exits (broker figures) fill the gaps the ledger
    # has not absorbed yet; the ledger's own figures always win.
    per_exit = dict(ledger["perExit"])
    for ticker, value in (pending or {}).items():
        per_exit.setdefault(ticker, value)
    prev_rules = {e.get("ticker"): e.get("rule") for e in prev_exits}
    rows = []
    for e in gen_exits:
        ticker = e.get("ticker")
        if ticker not in per_exit:
            raise RefreshError(
                f"Ledger has no realized figure for the {ticker} exit — "
                "the exit log cannot be reconciled."
            )
        rule = money_in_text((e.get("rule") or "").strip())
        if not rule:
            rule = prev_rules.get(ticker) or ""
        if not rule:
            raise RefreshError(f"No rule text for the {ticker} exit.")
        rows.append({
            "ticker": ticker,
            "exitDate": short_date(str(e.get("closed"))),
            "pnl": per_exit[ticker],
            "rule": rule,
            "_date": str(e.get("closed")),
        })
    if "GRAB_CALLS" not in per_exit or "INHERITED" not in per_exit:
        raise RefreshError(
            "Ledger is missing the GRAB-calls or day-one realized figure."
        )
    rows.append({
        "ticker": "GRAB calls", "exitDate": "Oct 20",
        "pnl": per_exit["GRAB_CALLS"],
        "rule": "Nov $3.00 calls hit the -50% premium line — exited at the open.",
        "_date": "2026-10-20",
    })
    rows.append({
        "ticker": "Inherited book", "exitDate": "Sep 18",
        "pnl": per_exit["INHERITED"],
        "rule": ("Day one: 16 inherited positions liquidated in the planned "
                 "consolidation — AVAT was the only winner."),
        "_date": "2026-09-18",
    })
    rows.sort(key=lambda r: r["_date"], reverse=True)
    total = round(sum(r["pnl"] for r in rows), 2)
    expected = round(
        ledger["realizedCum"] + sum((pending or {}).values()), 2)
    if abs(total - expected) > 0.011:
        raise RefreshError(
            f"Exit log sums to {fmt_money(total)} but the ledger's realized "
            f"total is {fmt_money(expected)} — not publishing."
        )
    for r in rows:
        del r["_date"]
    return rows


def translate_watch(gen: dict, positions: list, prev_watch: list,
                    today: date_cls, phase: str) -> list:
    prev_by_key = {}
    for w in prev_watch:
        prev_by_key[(w.get("dateLabel"), (w.get("title") or "").split(" ")[0])] = w
    prev_by_title = {w.get("title"): w for w in prev_watch}
    dated: list[tuple[str, dict]] = []

    for ev in gen.get("next_events", []):
        iso = str(ev.get("date"))
        ticker = ev.get("ticker") or ""
        event = (ev.get("event") or "").strip()
        dl = label_date(iso, today)
        prev = prev_by_key.get((dl, ticker))
        if prev:
            title = prev["title"]
        else:
            short = re.sub(r"\s*\([^)]*\)\s*$", "", event)
            short = re.sub(r"\s+expected\s*$", "", short)
            if len(short) > 38:
                short = short[:38].rsplit(" ", 1)[0]
            title = f"{ticker} {short}".strip()
        # A far-out event must not read as imminent: say how far out it
        # is. (The Next card otherwise shows a date ~a year away with
        # no sense of distance.)
        detail = event
        far = (date_cls.fromisoformat(iso) - today).days
        if far > 30:
            detail = f"{event} — ~{max(1, far // 30)} mo out"
        dated.append((iso, {"dateLabel": dl, "title": title, "detail": detail}))

    price_word = "close" if phase == "close" else "last"
    for p in positions:
        gen_card = next(
            (c for c in gen.get("positions", []) if c.get("ticker") == p["ticker"]),
            None,
        )
        if p["stopSuspended"] and gen_card:
            until = str(
                (gen_card.get("stock_gauge") or {}).get("exit_suspended_until")
            )
            title = f"{p['ticker']}'s {fmt_money(float(p['stopPrice']))} line re-arms"
            prev = prev_by_title.get(title)
            detail = prev["detail"] if prev else (
                f"The {fmt_money(float(p['stopPrice']))} mechanical stop was "
                f"suspended through its catalyst window; it goes live again "
                f"{label_date(until, today)}."
            )
            dated.append((until, {
                "dateLabel": label_date(until, today), "title": title, "detail": detail,
            }))

    # Carryover: still-future dated items from the previous board that the
    # generator cannot know (e.g. a macro print from the session notes).
    gen_labels = {dl for _, item in dated for dl in [item["dateLabel"]]}
    open_tickers = {p["ticker"] for p in positions}
    for w in prev_watch:
        dl = w.get("dateLabel") or ""
        title = w.get("title") or ""
        if "re-arms" in title or "take-profit at" in title:
            continue  # regenerated above / below
        try:
            # Labels carry their year when out-of-year; same-year labels
            # have none and take this year's.
            parsed = datetime.strptime(dl, "%a %b %d %Y").date()
        except ValueError:
            try:
                parsed = datetime.strptime(
                    f"{dl} {today.year}", "%a %b %d %Y"
                ).date()
            except ValueError:
                continue  # 'Resting' and other undated rows are not carried
        if parsed < today:
            continue  # date has passed
        if dl in gen_labels and title.split(" ")[0] in open_tickers:
            continue  # same event, regenerated from the generator
        dated.append((parsed.isoformat(), {
            "dateLabel": dl, "title": title, "detail": w.get("detail") or "",
        }))

    dated.sort(key=lambda t: t[0])
    items = [item for _, item in dated]

    # Resting native take-profit limits last.
    for p in positions:
        if p["kind"] != "Shares" or p["takeProfit"] is None:
            continue
        gen_card = next(
            (c for c in gen.get("positions", []) if c.get("ticker") == p["ticker"]),
            None,
        )
        qty = (gen_card.get("stock_gauge") or {}).get("take_profit_qty") \
            if gen_card else None
        pct = (gen_card.get("stock_gauge") or {}).get("pct_to_take_profit") \
            if gen_card else None
        detail = f"Sell limit for {qty}, good-til-cancelled"
        if pct is not None:
            detail += (
                f" — {abs(float(pct)):.1f}% above today's "
                f"{fmt_money(float(p['price']))} {price_word}."
            )
        else:
            detail += "."
        items.append({
            "dateLabel": "Resting",
            "title": f"{p['ticker']} take-profit at {fmt_money(float(p['takeProfit']))}",
            "detail": detail,
        })
    return items[:6]


def translate_paper(gen: dict) -> list:
    out = []
    for e in gen.get("paper", []):
        flagged = str(e.get("flagged") or "")
        try:
            when = short_date(flagged)
        except ValueError:
            when = flagged
        out.append({
            "ticker": e.get("ticker") or "",
            "note": e.get("thesis") or "",
            "refLabel": f"In @ {fmt_money(float(e.get('ref_price') or 0))} · {when}",
        })
    return out


# ---------------------------------------------------------------- main ----

def run(previous_board: dict | None) -> dict:
    started = time.monotonic()
    now_et = datetime.now(ET)
    today = now_et.date()
    today_iso = today.isoformat()
    hour = now_et.hour + now_et.minute / 60
    # Phases at the 15-minute cadence: morning before 11:00, midday until
    # the 16:00 close, close from 16:00 on (closing prints + the scored
    # ledger row). Only close-phase runs append the day's series point.
    phase = "morning" if hour < 11 else "midday" if hour < 16 else "close"

    sys.path.insert(0, str(ROOT / "packages"))
    from thesis.models import load_all  # noqa: E402

    theses = load_all()
    open_theses = [
        t for t in theses
        if t.status in ("INTACT", "WEAKENED")
        and t.position
        and (t.position.shares or t.position.contracts)
    ]
    if not open_theses:
        raise RefreshError("No open positions in the thesis files.")
    theses_by_ticker = {t.ticker: t for t in open_theses}
    open_tickers = [t.ticker for t in open_theses]

    # ---- 1. Live fetch -------------------------------------------------
    symbols = list(dict.fromkeys(open_tickers + ["QQQ", "SPY"]))
    quotes = fetch_quotes(symbols)
    portfolio = mcp_call("get_portfolio", {"account_number": AGENTIC_ACCOUNT})
    total = round(float(portfolio.get("total_value") or 0), 2)
    cash = round(float(portfolio.get("cash") or 0), 2)
    if total <= 0:
        raise RefreshError("Robinhood portfolio returned no account total.")

    equity_pos = mcp_call(
        "get_equity_positions", {"account_number": AGENTIC_ACCOUNT}
    )
    broker_qty = {
        p["symbol"]: float(p.get("quantity") or 0)
        for p in equity_pos.get("positions", [])
        if float(p.get("quantity") or 0) > 0
    }
    # Positions must match the thesis files' live positions — both ways.
    thesis_equity = {
        t.ticker: float(t.position.shares)
        for t in open_theses if t.position.shares
    }
    if set(broker_qty) != set(thesis_equity):
        raise RefreshError(
            f"Broker equity positions {sorted(broker_qty)} do not match the "
            f"thesis files {sorted(thesis_equity)} — not publishing."
        )
    for ticker, qty in thesis_equity.items():
        if abs(broker_qty[ticker] - qty) > 0.001:
            raise RefreshError(
                f"Broker holds {broker_qty[ticker]} {ticker} but the thesis "
                f"file says {qty} — not publishing."
            )

    # Option marks: find each open option's live contract and quote it.
    prices: dict[str, float] = {t: quotes[t]["price"] for t in open_tickers}
    option_prev: dict[str, float] = {}
    option_theses = [t for t in open_theses if t.position.contracts]
    if option_theses:
        opt_pos = mcp_call(
            "get_option_positions", {"account_number": AGENTIC_ACCOUNT}
        )
        live_opts = [
            p for p in opt_pos.get("positions", [])
            if p.get("type") == "long" and float(p.get("quantity") or 0) > 0
        ]
        for t in option_theses:
            match = next(
                (p for p in live_opts if p.get("chain_symbol") == t.ticker),
                None,
            )
            if match is None:
                raise RefreshError(
                    f"No live option position for {t.ticker} at the broker."
                )
            if abs(float(match["quantity"]) - float(t.position.contracts)) > 0.001:
                raise RefreshError(
                    f"Broker holds {match['quantity']} {t.ticker} contracts "
                    f"but the thesis file says {t.position.contracts}."
                )
            qdata = mcp_call(
                "get_option_quotes", {"instrument_ids": [match["option_id"]]}
            )
            results = qdata.get("results", [])
            if not results:
                raise RefreshError(f"No live option quote for {t.ticker}.")
            q = results[0].get("quote", {})
            mark = q.get("adjusted_mark_price") or q.get("mark_price")
            if not mark or float(mark) <= 0:
                raise RefreshError(f"Option quote for {t.ticker} is empty.")
            prices[f"{t.ticker}_PREMIUM"] = float(mark)
            close_px = (results[0].get("close") or {}).get("price")
            prev = float(close_px) if close_px else (
                float(q["previous_close_price"])
                if q.get("previous_close_price") else None
            )
            if prev is None or prev <= 0:
                raise RefreshError(
                    f"No prior close for the {t.ticker} option — day move "
                    "cannot be computed."
                )
            option_prev[t.ticker] = prev

    # ---- 2. Ledger reconciliation figures ------------------------------
    ledger = parse_ledger()

    # ---- 3. Computed scorecard figures ---------------------------------
    def pct(now: float, base: float) -> float:
        return round((now / base - 1) * 100, 2)

    acct_cum = pct(total, ACCT_BASELINE)
    qqq_cum = pct(quotes["QQQ"]["price"], QQQ_BASELINE)
    spy_cum = pct(quotes["SPY"]["price"], SPY_BASELINE)
    gap_pp = round(acct_cum - qqq_cum, 2)
    spy_gap_pp = round(acct_cum - spy_cum, 2)
    day_qqq = pct(quotes["QQQ"]["price"], quotes["QQQ"]["prev_close"])
    day_spy = pct(quotes["SPY"]["price"], quotes["SPY"]["prev_close"])
    # Prior-session total reconstructed from the same live feed: current
    # cash + every position valued at its official prior close. This is
    # the figure the ledger's live feed read within cents on 2026-11-10.
    prior_total = cash
    for ticker, qty in thesis_equity.items():
        prior_total += qty * quotes[ticker]["prev_close"]
    for t in option_theses:
        prior_total += (
            float(t.position.contracts) * option_prev[t.ticker] * 100
        )
    day_acct = pct(total, prior_total)
    cash_pct = round(cash / total * 100, 1)
    peak = max(ledger["peak"], total)
    drawdown = round((total / peak - 1) * 100, 2)

    # ---- 4. Series maintenance ------------------------------------------
    series: list = []
    if SERIES_PATH.exists():
        series = json.loads(SERIES_PATH.read_text())
    elif previous_board and previous_board.get("series"):
        by_cum = {
            (s["acctPct"], s["qqqPct"]): d
            for d, s in ledger["sessions"].items()
        }
        for p in previous_board["series"]:
            d = by_cum.get((p["acctPct"], p["qqqPct"]))
            if d is None:
                raise RefreshError(
                    "series.json is missing and a previous point cannot be "
                    "dated from the ledger — not publishing."
                )
            series.append({
                "date": d, "label": p["dateLabel"],
                "acctPct": p["acctPct"], "qqqPct": p["qqqPct"],
                "spyPct": p.get("spyPct"),
            })
    if not series:
        raise RefreshError("No race series available — not publishing.")
    if phase == "close":
        sess = ledger["sessions"].get(today_iso)
        if sess is not None:
            point = {
                "date": today_iso,
                "label": short_date(today_iso),
                "acctPct": sess["acctPct"],
                "qqqPct": sess["qqqPct"],
                "spyPct": pct(quotes["SPY"]["price"], SPY_BASELINE),
            }
            series = [p for p in series if p.get("date") != today_iso]
            series.append(point)
            series.sort(key=lambda p: p.get("date", ""))
            SERIES_PATH.write_text(json.dumps(series) + "\n")

    # ---- 5. Generator ----------------------------------------------------
    account_arg = {
        "total": total, "cash": cash,
        "qqq_gap_pp": gap_pp, "spy_gap_pp": spy_gap_pp,
        "day_change_usd": round(total - prior_total, 2),
        "day_gap_vs_qqq_pp": round(day_acct - day_qqq, 2),
    }
    gen_run = subprocess.run(
        [sys.executable, str(GENERATOR),
         "--prices", json.dumps(prices),
         "--account", json.dumps(account_arg),
         "--as-of", today_iso,
         "--series", str(SERIES_PATH)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    if gen_run.returncode != 0:
        raise RefreshError(
            f"Board generator failed: {(gen_run.stderr or gen_run.stdout).strip()[:300]}"
        )
    gen = json.loads((HERE / "board.private.json").read_text())
    gen_gap = (gen.get("scorecard") or {}).get("qqq_gap_pp")
    if gen_gap is None or abs(float(gen_gap) - gap_pp) > 0.05:
        raise RefreshError(
            "Generator gap does not match the computed gap — not publishing."
        )
    if len(gen.get("positions", [])) != len(open_theses):
        raise RefreshError(
            "Generator positions do not match the thesis files' live "
            "positions — not publishing."
        )

    # ---- 6. Translate ------------------------------------------------------
    positions = translate_positions(
        gen.get("positions", []), theses_by_ticker, phase, today_iso
    )
    pending = pending_exits(gen.get("exits", []), ledger)
    exits = translate_exits(
        gen.get("exits", []), ledger,
        (previous_board or {}).get("exits", []), pending,
    )
    watch = translate_watch(
        gen, positions, (previous_board or {}).get("watchItems", []),
        today, phase,
    )
    paper = translate_paper(gen)

    weekday = f"{today:%a %b} {today.day}"
    board = {
        "scorecard": {
            "asOfLabel": f"{weekday} · {phase}",
            "accountValue": total,
            "cash": cash,
            "cashPct": cash_pct,
            "acctCumPct": acct_cum,
            "qqqCumPct": qqq_cum,
            "spyCumPct": spy_cum,
            "gapPp": gap_pp,
            "dayAcctPct": day_acct,
            "dayQqqPct": day_qqq,
            "daySpyPct": day_spy,
            "peakValue": peak,
            "drawdownPct": drawdown,
            "realizedCum": round(
                ledger["realizedCum"] + sum(pending.values()), 2),
        },
        "series": [
            {"dateLabel": p.get("label"), "acctPct": p.get("acctPct"),
             "qqqPct": p.get("qqqPct"), "spyPct": p.get("spyPct")}
            for p in series
        ],
        "positions": positions,
        "exits": exits,
        "watchItems": watch,
        "paperEntries": paper,
    }

    # ---- 7. Final sanity checks -------------------------------------------
    if previous_board and previous_board.get("scorecard"):
        prev_total = float(previous_board["scorecard"].get("accountValue") or 0)
        if prev_total > 0 and abs(total - prev_total) / prev_total > ACCOUNT_BAND:
            raise RefreshError(
                f"Account value {fmt_money(total)} is outside the sane band "
                f"around the last saved {fmt_money(prev_total)} — not publishing."
            )
    if cash < 0 or cash > total:
        raise RefreshError("Cash is outside the account total — not publishing.")
    for p in positions:
        if not p["price"] or p["price"] <= 0:
            raise RefreshError(f"Position {p['ticker']} has no live price.")

    return {
        "ok": True,
        "elapsedMs": round((time.monotonic() - started) * 1000),
        "board": board,
    }


_LOCK_FD = None  # held for the process lifetime (single-flight)


def _acquire_lock() -> bool:
    global _LOCK_FD
    import fcntl

    fd = os.open(HERE / ".refresh.lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    _LOCK_FD = fd
    return True


def _in_scheduled_window(now_et: datetime) -> bool:
    """Weekdays, 9:30–16:30 ET (30 min past the close so the day's scored
    series point lands on a scheduled run)."""
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60 + 30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous-board", default=None,
                    help="JSON file with the currently saved board (or null)")
    ap.add_argument("--out", default=None,
                    help="write the result JSON here (default: stdout)")
    ap.add_argument("--scheduled", action="store_true",
                    help="scheduled run: no-op outside market hours")
    args = ap.parse_args()

    started = time.monotonic()

    if args.scheduled and not _in_scheduled_window(datetime.now(ET)):
        result = {
            "ok": True, "skipped": True,
            "reason": "outside market hours",
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }
        if args.out:
            Path(args.out).write_text(json.dumps(result) + "\n")
        print("refresh skipped: outside market hours")
        return 0

    if not _acquire_lock():
        result = {
            "ok": False,
            "elapsedMs": round((time.monotonic() - started) * 1000),
            "error": "A refresh is already running — give it a few seconds.",
        }
        if args.out:
            Path(args.out).write_text(json.dumps(result) + "\n")
        print(f"refresh FAILED in {result['elapsedMs']}ms: {result['error']}")
        return 2

    previous_board = None
    if args.previous_board:
        raw = Path(args.previous_board).read_text().strip()
        if raw and raw != "null":
            previous_board = json.loads(raw)

    try:
        result = run(previous_board)
    except RefreshError as e:
        result = {
            "ok": False,
            "elapsedMs": round((time.monotonic() - started) * 1000),
            "error": str(e),
        }
    except Exception as e:  # noqa: BLE001 — fail loudly, never save
        result = {
            "ok": False,
            "elapsedMs": round((time.monotonic() - started) * 1000),
            "error": f"Refresh failed: {e}",
        }

    payload = json.dumps(result)
    if args.out:
        Path(args.out).write_text(payload + "\n")
    print(
        f"refresh {'ok' if result['ok'] else 'FAILED'} "
        f"in {result['elapsedMs']}ms"
        + ("" if result["ok"] else f": {result['error']}")
    )
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
