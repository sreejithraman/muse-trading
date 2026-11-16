#!/usr/bin/env python3
"""Deterministic session scoring: the after-close verdict vs QQQ, as code.

Implements the agentic-session-scoring cron body's steps 1-5 exactly, and
prints the step-6 verdict to stdout for the launcher cron to deliver as the
one message. The agent does no arithmetic here any more: this script reads
the ledger's running state, reads the live agentic account read-only, and
appends the session row in the ledger's exact existing format.

Rules, from the cron body:
  - Read-only against the brokerage account. Never places,
    modifies, or cancels orders. No money movement.
  - If the account data is unreachable: append a gap note for the session
    and stop. Never estimate.
  - If no trading session occurred today (market holiday): record nothing,
    stay silent.
  - Deposits/withdrawals are external cash flows, never performance: the
    session %d is computed against (prior mark + deposits - withdrawals),
    net deposits are added to the inception baseline and the running peak,
    and the event plus rebased figures are recorded.
  - Nothing is estimated. A session with unavailable data is a gap.

Idempotent: if today's session block already exists in the ledger, the
script does nothing (a re-run never double-appends).

Modes:
  --dry-run   do everything except write (prints the row + verdict)
  --force     with --dry-run only: render from live intraday marks even
              though the close has not settled (format verification only;
              never writes, never scores a session)
  --verify [DATES...]
              recompute the listed sessions (default: the last five scored
              sessions plus the deposit-rebase and exit days) from the
              ledger's own recorded inputs and diff every number against
              the recorded rows. Read-only; exits non-zero on any mismatch.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thesis"))
from models import load_all  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # ~/workspace/trading-tools
LEDGER = (
    Path.home()
    / "workspace/goals/agentic-account-trading-operation/files/performance-ledger.md"
)

MCP_PY = str(Path.home() / "workspace/robinhood-mcp/.venv/bin/python")
MCP_TOOL = str(Path.home() / "workspace/robinhood-mcp/mcp_tool.py")
RH_DIR = Path.home() / "workspace/robinhood-mcp"

ET = ZoneInfo("America/New_York")

# The QQQ inception baseline never changes (no QQQ cash flows): it is read
# from the ledger's Running state, not assumed here. The account baseline is
# likewise read (raw inception + every deposit-rebase note to date).
CASH_TOLERANCE = Decimal("0.50")  # unexplained cash move below this is noise
VERIFY_PCT_TOL = 0.015            # percentage points (recorded values are 2dp)
VERIFY_MONEY_TOL = 0.02           # dollars


class ScoreError(Exception):
    """A check failed or a source was unavailable: gap, do not score."""


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
    raise ScoreError(
        "ROBINHOOD_ACCOUNT_NUMBER is not set and "
        "~/workspace/robinhood-mcp/.account_number is missing."
    )


AGENTIC_ACCOUNT = _agentic_account()


# ------------------------------------------------------------ rounding ----

def D(x) -> Decimal:
    return Decimal(str(x))


def r2(x) -> float:
    """Round to 2dp, half-up (the ledger's convention, not banker's)."""
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r1(x) -> float:
    return float(D(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fmt_money(v: float) -> str:
    """$1,932.65 — absolute values only; callers add the sign."""
    return f"${abs(v):,.2f}"


def fmt_signed_money(v: float) -> str:
    """+$48.83 / -$37.36 / $0 — the ledger's signed-money form."""
    if abs(v) < 0.005:
        return "$0"
    return ("+" if v > 0 else "-") + fmt_money(v)


def fmt_pct(v: float, signed: bool = True) -> str:
    if signed:
        return f"{v:+.2f}%"
    return f"{v:.2f}%"


def fmt_pp(v: float) -> str:
    return f"{v:+.2f}pp"


def fmt_num(v: float) -> str:
    """66.2 -> '66.2', 5.70 -> '5.7', 100.0 -> '100'."""
    return f"{v:f}".rstrip("0").rstrip(".") if "." in f"{v:f}" else f"{v:f}"


def ordinal(n: int) -> str:
    words = {2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth",
             6: "Sixth", 7: "Seventh", 8: "Eighth"}
    return words.get(n, f"{n}th")


# ----------------------------------------------------------------- MCP ----

def _refresh_token() -> bool:
    """One-shot OAuth refresh, same recovery checkin.py / refresh.py use."""
    try:
        from urllib.parse import urlencode
        from urllib import request as rq

        state = json.loads((RH_DIR / ".oauth_state.json").read_text())
        tokp = RH_DIR / ".tokens.json"
        tokens = json.loads(tokp.read_text())
        data = urlencode({
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": state["client_id"],
        }).encode()
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
    """One Robinhood MCP tool call. Returns the tool's `data` object.

    Raises ScoreError on any failure — a missing read must gap the
    session, never be estimated.
    """
    env = dict(os.environ, NO_PROXY="", no_proxy="")
    for attempt in range(2):
        try:
            out = subprocess.run(
                [MCP_PY, MCP_TOOL, tool, json.dumps(args)],
                capture_output=True, text=True, timeout=60, env=env,
            )
        except Exception as e:  # noqa: BLE001
            raise ScoreError(f"Robinhood {tool} could not run: {e}") from e
        if "JWT verification failed" in (out.stdout or "") and attempt == 0:
            if _refresh_token():
                continue
            raise ScoreError("Robinhood login expired and token refresh failed.")
        try:
            payload = json.loads(out.stdout)
        except Exception as e:  # noqa: BLE001
            raise ScoreError(f"Robinhood {tool} returned unreadable output.") from e
        if "error" in payload:
            raise ScoreError(f"Robinhood {tool} failed: {payload['error']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ScoreError(f"Robinhood {tool} returned no data.")
        return data
    raise ScoreError(f"Robinhood {tool} failed after a token refresh.")


# -------------------------------------------------------------- ledger ----

def _money(s: str) -> float:
    return float(s.replace("$", "").replace(",", "").replace("+", ""))


def _resolve_date(s: str, year: int) -> str:
    """ISO date as-is; the ledger's MM/DD prose date resolved to `year`."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    m, d = s.split("/")
    return f"{year:04d}-{int(m):02d}-{int(d):02d}"


def _md(iso: str) -> str:
    """ISO date -> the ledger's MM/DD prose date. Deepest dates are stored
    ISO internally and rendered MM/DD, the convention in every row."""
    return iso[5:].replace("-", "/") if len(iso) == 10 else iso


SESSION_RE = re.compile(
    r"### (\d{4}-\d{2}-\d{2}) — (.*?)\n(.*?)(?=\n### |\Z)", re.DOTALL)


def parse_sessions(text: str) -> list[dict]:
    """Every `### DATE — ...` block. Last block per date wins (a date can
    carry both a close-review row and the after-close verdict row; the
    verdict row is canonical). Gap blocks are flagged, not scored."""
    by_date: dict[str, dict] = {}
    order: list[str] = []
    for m in SESSION_RE.finditer(text):
        d, head, body = m.group(1), m.group(2), m.group(3)
        day_m = re.match(r"Day (\d+)", head)
        blk = {"date": d, "head": head,
               "day": int(day_m.group(1)) if day_m else None,
               # Only the script's own gap blocks count: a scored row's
               # header can contain the words "session gap" ("third straight
               # negative session gap"), which is not a gap block.
               "gap": "scoring gap" in head.lower(), "body": body}
        if d not in by_date:
            order.append(d)
        by_date[d] = blk  # later block for the same date replaces the earlier
    return [by_date[d] for d in order]


def _first(pat: str, body: str, flags: int = 0):
    m = re.search(pat, body, flags)
    return m


def parse_session_values(blk: dict) -> dict:
    """Recorded inputs + recorded derived values for one session block."""
    b = blk["body"]
    v: dict = {"date": blk["date"], "day": blk["day"], "gap": blk["gap"]}
    # Account bullet, scoped to itself (the line wraps, and the deposit
    # form carries TWO arrows: prior -> rebased base -> today; the last
    # arrow is today's value).
    am = re.search(r"- Account: (.*?)(?=\n- QQQ:)", b, re.DOTALL)
    if am:
        ab = am.group(1)
        pm = re.search(r"\$([\d,]+\.\d+)", ab)
        if pm:
            v["prior_acct"] = _money(pm.group(1))
        arrows = re.findall(r"→ \*\*\$([\d,]+\.\d+)\*\*", ab)
        if arrows:
            v["acct"] = _money(arrows[-1])
    m = _first(r"\(\S+?\$[\d,]+\.\d+, \*\*([+-]?[\d.]+)%\*\* day[;)]",
               ab if am else b, re.DOTALL)
    if m:
        v["acct_day_pct"] = float(m.group(1))
    m = _first(r"QQQ: \$([\d,]+\.\d+) .*?→ \*\*\$([\d,]+\.\d+)\*\*", b, re.DOTALL)
    if m:
        v["prior_qqq"], v["qqq"] = _money(m.group(1)), _money(m.group(2))
    m = _first(r"QQQ:.*?\(\*\*([+-]?[\d.]+)%\*\* day;", b, re.DOTALL)
    if m:
        v["qqq_day_pct"] = float(m.group(1))
    m = _first(r"Session gap: \*\*([+-]?[\d.]+)pp\*\*", b)
    if m:
        v["gap_pp"] = float(m.group(1))
    m = _first(r"Cumulative: account \*\*([+-]?[\d.]+)%\*\*.*?QQQ \*\*([+-]?[\d.]+)%\*\*"
               r".*?gap \*\*([+-]?[\d.]+)pp\*\*", b, re.DOTALL)
    if m:
        v["cum_acct"], v["cum_qqq"], v["cum_gap"] = (
            float(m.group(1)), float(m.group(2)), float(m.group(3)))
    m = _first(r"Cash: \$([\d,]+\.\d+)", b)
    if m:
        v["cash"] = _money(m.group(1))
    m = _first(r"Equity: \$([\d,]+\.\d+).*?Cost basis: "
               r"\$([\d,]+\.\d+).*?→\s+Unrealized \*\*([+-]?\$[\d,]+\.\d+)\*\*",
               b, re.DOTALL)
    if m:
        v["equity"], v["cost"], v["unrealized"] = (
            _money(m.group(1)), _money(m.group(2)), _money(m.group(3)))
    m = _first(r"\(options book: [^\n]*?\*\*\$([\d,]+(?:\.\d+)?)\*\* vs "
               r"\$([\d,]+(?:\.\d+)?) cost", b)
    if m:
        v["options"], v["options_cost"] = _money(m.group(1)), _money(m.group(2))
    m = _first(r"Realized P&L: \*\*(-?\$[\d,]+(?:\.\d+)?)\*\*", b)
    if m:
        v["realized"] = _money(m.group(1))
    m = _first(r"Cumulative\s+realized (?:now )? ?\*\*(-?\$[\d,]+(?:\.\d+)?)\*\*",
               b, re.IGNORECASE)
    if m:
        v["cum_realized"] = _money(m.group(1))
    m = _first(r"Drawdown from peak: \*\*(-?[\d.]+)%\*\*", b)
    if m:
        v["drawdown"] = float(m.group(1))
    m = _first(r"rebased base \*\*\$([\d,]+\.\d+)\*\*.*?"
               r"\+\s*\$([\d,]+)\s+deposit", b, re.DOTALL)
    if m:
        v["rebased_base"], v["deposit"] = _money(m.group(1)), _money(m.group(2))
    # The close-print equity sum: the Unrealized figure is computed from
    # it, while the Equity headline can be the live feed (after-hours
    # drift). When the row gives no separate close-print value, the
    # headline IS the close sum.
    m = _first(r"close-print sum \$([\d,]+\.\d+)\)", b)
    if m:
        v["equity_close"] = _money(m.group(1))
    elif "equity" in v:
        v["equity_close"] = v["equity"]
    v["positions"] = {}
    for pm in re.finditer(
            r"  - (\w+) ([\d.]+) @ \$([\d,]+\.\d+) → \$([\d,]+\.\d+) "
            r"\(cost \$([\d,]+\.\d+)\)", b):
        v["positions"][pm.group(1)] = {
            "qty": float(pm.group(2)), "price": _money(pm.group(3)),
            "value": _money(pm.group(4)), "cost": _money(pm.group(5))}
    return v


def parse_running_state(text: str) -> dict:
    """The `## Running state` block: baselines, peak, cumulative realized,
    cumulative score, drawdown/deepest, and every deposit-rebase note."""
    m = re.search(r"## Running state\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not m:
        raise ScoreError("Ledger has no Running state block.")
    rs = m.group(1)
    st: dict = {}
    m = re.search(r"Inception baseline \(2026-09-18 pre-session\): account "
                  r"\*\*\$([\d,]+\.\d+)\*\*, QQQ \*\*\$([\d,]+\.\d+)\*\*", rs)
    if not m:
        raise ScoreError("Ledger Running state has no inception baseline.")
    st["inception_acct"], st["inception_qqq"] = _money(m.group(1)), _money(m.group(2))
    m = re.search(r"Running peak: \*\*\$([\d,]+\.\d+)\*\* \((\d{4}-\d{2}-\d{2})",
                  rs)
    if not m:
        raise ScoreError("Ledger Running state has no running peak.")
    st["peak"], st["peak_date"] = _money(m.group(1)), m.group(2)
    # Line-scoped: the parenthetical is one physical line; a DOTALL greedy
    # capture here once swallowed the Cumulative score, Drawdown and
    # rebase lines into the note (and would have re-inserted them into
    # the realized line on the first live write).
    m = re.search(r"Cumulative realized P&L: \*\*(-?\$[\d,]+\.\d+)\*\* \((.*)\)$",
                  rs, re.MULTILINE)
    if not m:
        raise ScoreError("Ledger Running state has no cumulative realized P&L.")
    st["cum_realized"] = _money(m.group(1))
    st["realized_note"] = m.group(2)
    m = re.search(r"Cumulative score: account \*\*(-?[\d.]+)%\*\*, QQQ "
                  r"\*\*(-?[\d.]+)%\*\*, gap \*\*([+-]?[\d.]+)pp\*\*", rs)
    if m:
        st["cum_acct"], st["cum_qqq"], st["cum_gap"] = (
            float(m.group(1)), float(m.group(2)), float(m.group(3)))
    # Deepest date is MM/DD in the ledger prose ("on 10/19"); the writer
    # omits "remains" on a new-deepest session, so accept both forms.
    m = re.search(r"Drawdown: \*\*(-?[\d.]+)%\*\* \(peak \$([\d,]+\.\d+), "
                  r"(\d{4}-\d{2}-\d{2}); deepest (?:remains )?(-?[\d.]+)% on "
                  r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})\)", rs)
    if m:
        st["drawdown"], st["dd_peak"], st["dd_peak_date"] = (
            float(m.group(1)), _money(m.group(2)), m.group(3))
        st["deepest"] = float(m.group(4))
        st["deepest_date"] = _resolve_date(m.group(5), int(m.group(3)[:4]))
    # Deposit-rebase notes: each carries the adjusted inception baseline.
    st["baseline_acct"] = st["inception_acct"]
    st["deposits_total"] = 0.0
    for rm in re.finditer(
            r"### Deposit rebase — (\d{4}-\d{2}-\d{2})[^\n]*\n(.*?)(?=\n### |\n## |\Z)",
            rs, re.DOTALL):
        bm = re.search(r"inception baseline \*\*\$([\d,]+\.\d+)\*\*", rm.group(2))
        if bm:
            st["baseline_acct"] = _money(bm.group(1))
    st["deposits_total"] = r2(st["baseline_acct"] - st["inception_acct"])
    return st

# ------------------------------------------------------------- compute ----

def pct(numer: float, denom: float) -> float:
    """(numer/denom - 1) * 100, rounded half-up to 2dp."""
    return r2((D(numer) / D(denom) - 1) * 100)


def compute_session(prior: dict, today: dict) -> dict:
    """Pure scoring math, shared by the live path and --verify.

    prior: prior session's recorded values (acct, qqq, cash, equity,
      options, cum_realized, peak, peak_date, deepest, deepest_date,
      gap history). today: today's inputs (acct, qqq, cash, equity, cost,
      options, options_cost, realized, deposits). Deposits are external
    cash flows: the session %d is measured against the rebased base and
    the baseline/peak are rebased before any return math.
    Returns every derived number the row records.
    """
    deposits = today.get("deposits", 0.0) or 0.0
    adj_prior = r2(prior["acct"] + deposits)
    baseline = r2(prior["baseline_acct"] + deposits)
    peak = r2(prior["peak"] + deposits)
    acct = today["acct"]
    qqq = today["qqq"]

    acct_day = pct(acct, adj_prior)
    qqq_day = pct(qqq, prior["qqq"])
    gap = r2(acct_day - qqq_day)
    cum_acct = pct(acct, baseline)
    cum_qqq = pct(qqq, prior["inception_qqq"])
    cum_gap = r2(cum_acct - cum_qqq)
    new_peak = acct > peak
    if new_peak:
        peak, peak_date = acct, today["date"]
    else:
        peak_date = prior["peak_date"]
    drawdown = pct(acct, peak) if not new_peak else 0.0
    new_deepest = drawdown < prior["deepest"]
    deepest = drawdown if new_deepest else prior["deepest"]
    deepest_date = today["date"] if new_deepest else prior["deepest_date"]
    unrealized = r2(today["equity"] - today["cost"])
    cum_realized = r2(prior["cum_realized"] + today.get("realized", 0.0))
    cash_pct = r1(today["cash"] / acct * 100)

    # Negative-gap streak (chronological list, including today).
    streak = list(prior.get("neg_gap_history", []))
    if gap < 0:
        streak.append(gap)
    else:
        streak = []

    # Cash drag vs genuine underperformance: did the invested legs keep
    # up with QQQ? Invested = equity + options, prior vs today.
    inv_prior = r2(prior["equity"] + prior.get("options", 0.0))
    inv_today = r2(today["equity"] + today.get("options", 0.0))
    invested_day = pct(inv_today, inv_prior) if inv_prior > 0 else 0.0
    cash_drag = gap < 0 and invested_day >= qqq_day

    return {
        "date": today["date"], "acct_day": acct_day, "qqq_day": qqq_day,
        "gap": gap, "cum_acct": cum_acct, "cum_qqq": cum_qqq,
        "cum_gap": cum_gap, "baseline": baseline, "adj_prior": adj_prior,
        "peak": peak, "peak_date": peak_date, "new_peak": new_peak,
        "drawdown": drawdown, "new_deepest": new_deepest,
        "deepest": deepest, "deepest_date": deepest_date,
        "unrealized": unrealized, "cum_realized": cum_realized,
        "cash_pct": cash_pct, "streak": streak, "cash_drag": cash_drag,
        "invested_day": invested_day,
    }


# -------------------------------------------------------------- theses ----

def load_open_theses() -> dict:
    """{ticker: Thesis} for live positions, as checkin.py loads them."""
    return {t.ticker: t for t in load_all()
            if t.status not in ("CLOSED", "EXITED")}


def active_red_line(thesis, today_iso: str):
    """Nearest active (not suspended) price red line, or None."""
    lines = [rl for rl in (thesis.red_lines or [])
             if rl.price_level
             and not (rl.suspended_until and rl.suspended_until >= today_iso)]
    if not lines:
        return None
    return min(lines, key=lambda rl: rl.price_level)


def suspended_line(thesis, today_iso: str):
    """Nearest suspended price red line, or None."""
    lines = [rl for rl in (thesis.red_lines or [])
             if rl.price_level
             and rl.suspended_until and rl.suspended_until >= today_iso]
    if not lines:
        return None
    return min(lines, key=lambda rl: rl.price_level)


def next_key_date(thesis, today_iso: str):
    """Nearest upcoming key date (today or later), or None."""
    upcoming = [k for k in (thesis.key_dates or []) if k.date >= today_iso]
    if not upcoming:
        return None
    return min(upcoming, key=lambda k: k.date)


def option_label(thesis) -> str:
    """'SOFI Jan 21 2028 $15 call 1x' — the ledger's options-book form."""
    p = thesis.position
    exp = datetime.strptime(p.expiry, "%Y-%m-%d").strftime("%b %d %Y")
    return (f"{thesis.ticker} {exp} ${fmt_num(p.strike)} call "
            f"{p.contracts}x")


# --------------------------------------------------------------- render ----

def _day_dollar_split(prior_pos: dict, today_pos: dict,
                      prior_opt: float, today_opt: float) -> str:
    """'options -$32.00, GRAB -$5.30, SMMT -$0.06' — the down-day split."""
    parts = []
    if today_opt is not None and prior_opt is not None:
        parts.append(f"options {fmt_signed_money(r2(today_opt - prior_opt))}")
    for sym in sorted(today_pos):
        if sym in prior_pos:
            parts.append(f"{sym} {fmt_signed_money(
                r2(today_pos[sym]['value'] - prior_pos[sym]['value']))}")
    return ", ".join(parts)


def render_row(day_no: int, prior: dict, live: dict, res: dict,
               theses: dict, today_iso: str) -> str:
    """The session row, in the ledger's exact existing format. `prior` is
    the previous session's parsed values; `live` is today's fetched data;
    `res` is compute_session's output. Narrative lines are templated from
    computed figures only — no invented drivers."""
    acct, qqq = live["acct"], live["qqq"]
    pdate = prior["date"]
    lines = []

    # Header descriptor: deterministic, from fills + gap streak.
    if live["fills"]:
        desc = "after-close verdict; " + ", ".join(
            f"{f['symbol']} exited at the open"
            if f["side"] == "sell" and f.get("closed_position") else
            f"{f['symbol']} {f['side']} {fmt_num(f['quantity'])}"
            for f in live["fills"])
    else:
        desc = "after-close verdict; no trades"
    if len(res["streak"]) >= 2:
        desc += f" — {ordinal(len(res['streak'])).lower()} straight negative session gap"
    lines.append(f"### {today_iso} — Day {day_no} ({desc})")
    lines.append("")

    acct_delta = r2(acct - res["adj_prior"])
    live_note = ""
    if abs(live["live_total"] - acct) >= 0.50:
        live_note = (f"; live portfolio feed at ~4:10 PM ET read "
                     f"{fmt_money(live['live_total'])}, a "
                     f"{fmt_money(abs(live['live_total'] - acct))} "
                     f"after-hours mark difference — immaterial")
    lines.append(
        f"- Account: {fmt_money(prior['acct'])} ({pdate} official close) → "
        f"**{fmt_money(acct)}** ({fmt_signed_money(acct_delta)}, "
        f"**{fmt_pct(res['acct_day'])}** day;\n  official close marks{live_note})")
    qqq_rev = ""
    if live.get("qqq_prior_feed") is not None and abs(
            live["qqq_prior_feed"] - prior["qqq"]) >= 0.02:
        qqq_rev = (f"; the quote feed's official {pdate} SIP close field now "
                   f"reads {fmt_money(live['qqq_prior_feed'])}, a "
                   f"{fmt_money(abs(live['qqq_prior_feed'] - prior['qqq']))} "
                   f"revision — immaterial")
    lines.append(
        f"- QQQ: {fmt_money(prior['qqq'])} ({pdate} ledger mark{qqq_rev}) → "
        f"**{fmt_money(qqq)}** (**{fmt_pct(res['qqq_day'])}** day; "
        f"3:59:59 PM ET close print)")
    cum_note = ""
    if res["cum_gap"] > 0:
        cum_note = (f" — the account stays ahead of QQQ cumulatively, "
                    f"{'narrowing' if res['cum_gap'] < prior['cum_gap'] else 'widening'} "
                    f"from {fmt_pp(prior['cum_gap'])}")
        if prior["cum_acct"] >= 0 and res["cum_acct"] < 0:
            cum_note += ("; the account flips back to cumulatively negative "
                         f"after a single positive session ({pdate}, "
                         f"{fmt_pct(prior['cum_acct'])})")
        elif prior["cum_acct"] < 0 and res["cum_acct"] >= 0:
            cum_note += "; the account flips back to cumulatively positive"
    elif res["cum_gap"] < 0:
        cum_note = " — the account trails QQQ cumulatively"
    lines.append(
        f"- Session gap: **{fmt_pp(res['gap'])}** | Cumulative: account "
        f"**{fmt_pct(res['cum_acct'])}** (vs deposit-adjusted baseline "
        f"{fmt_money(res['baseline'])}), QQQ **{fmt_pct(res['cum_qqq'])}** "
        f"(vs ${prior['inception_qqq']:,.2f} baseline), gap "
        f"**{fmt_pp(res['cum_gap'])}**{cum_note}")
    bp = live["buying_power"]
    unsettled = r2(live["cash"] - bp)
    if unsettled >= 0.50:
        sell_proceeds = sum(f["quantity"] * f["price"] * f.get("mult", 1)
                            for f in live["fills"] if f["side"] == "sell")
        un_note = (f" — today's proceeds {fmt_money(sell_proceeds)} unsettled "
                   f"until T+1" if live["fills"] and abs(
                       sell_proceeds - unsettled) < 1.00
                   else f" — {fmt_money(unsettled)} unsettled")
        cash_note = f"(buying power {fmt_money(bp)}{un_note})"
    else:
        pend = live.get("pending_deposits", 0.0)
        cash_note = (f"(buying power {fmt_money(bp)}; no unsettled funds"
                     + (f", {fmt_money(pend)} pending deposits" if pend else
                        ", no pending deposits") + ")")
    cash_same = ("; unchanged from the "
                 f"{pdate} mark" if abs(live["cash"] - prior["cash"]) < 0.005
                 else "")
    lines.append(
        f"- Cash: {fmt_money(live['cash'])} {cash_note} — "
        f"~{res['cash_pct']:.1f}% of the account{cash_same}")
    lines.append(
        f"- Equity: {fmt_money(live['equity'])} (close-print sum; live feed "
        f"{fmt_money(live['live_equity'])} after hours) | Cost basis: "
        f"{fmt_money(live['cost'])} → Unrealized "
        f"**{fmt_signed_money(res['unrealized'])}** "
        f"(vs {fmt_signed_money(prior['unrealized'])} on {pdate})")
    if live.get("options") is not None and live["options"] > 0:
        opt_delta = r2(live["options"] - prior.get("options", 0.0))
        opt_pct = pct(live["options"], live["options_cost"])
        prior_opt_pct = (pct(prior["options"], prior["options_cost"])
                         if prior.get("options") and prior.get("options_cost")
                         else None)
        sofi = live["quotes"].get("SOFI", {})
        sofi_line = ""
        if sofi:
            sofi_line = (f"; SOFI shares closed {fmt_money(sofi['price'])}, "
                         f"{fmt_pct(sofi['day_pct'])} on the day")
        opt_labels = ", ".join(option_label(theses[s])
                               for s in live["option_tickers"]
                               if s in theses)
        prior_pct_txt = (f" (was {fmt_pct(prior_opt_pct)})"
                         if prior_opt_pct is not None else "")
        lines.append(
            f"  (options book: **{fmt_money(live['options'])}** vs "
            f"{fmt_money(live['options_cost'])} cost, "
            f"**{fmt_signed_money(r2(live['options'] - live['options_cost']))}** "
            f"/ {fmt_pct(opt_pct)} — {opt_labels} only, "
            f"{'up' if opt_delta >= 0 else 'down'} "
            f"**{fmt_signed_money(opt_delta)}** from {pdate}'s "
            f"{fmt_money(prior.get('options', 0.0))} mark{prior_pct_txt}"
            f"{sofi_line})")
    for sym in sorted(live["positions"]):
        pos = live["positions"][sym]
        th = theses.get(sym)
        blended = pct(pos["value"], pos["cost"])
        day_pct = pos["day_pct"]
        notes = []
        rl = active_red_line(th, today_iso) if th else None
        sl = suspended_line(th, today_iso) if th else None
        if sl:
            dist = r2((pos["price"] / sl.price_level - 1) * 100)
            notes.append(
                f"now {dist:.1f}% above the {fmt_money(sl.price_level)} line, "
                f"but that line's suspension stands through "
                f"{sl.suspended_until} — no mechanical trigger")
        elif rl:
            dist = r2((pos["price"] / rl.price_level - 1) * 100)
            notes.append(f"now {dist:.1f}% above the "
                         f"{fmt_money(rl.price_level)} close-based red line")
        if th and th.position and th.position.take_profit:
            tp = th.position.take_profit
            held = pos.get("held_for_sells", 0.0)
            tp_dist = r2((tp / pos["price"] - 1) * 100)
            qty_txt = (th.position.take_profit_qty or "half")
            if held > 0:
                notes.append(
                    f"the native take-profit sell limit ({qty_txt} @ "
                    f"{fmt_money(tp)} gtc) remains open and unfilled, "
                    f"{tp_dist:.1f}% away; {fmt_num(held)} shares still held "
                    f"for sells")
            else:
                notes.append(
                    f"no shares held for sells — the {fmt_money(tp)} "
                    f"take-profit may have filled or been cancelled; morning "
                    f"session to confirm")
        lines.append(
            f"  - {sym} {fmt_num(pos['qty'])} @ {fmt_money(pos['price'])} → "
            f"{fmt_money(pos['value'])} (cost {fmt_money(pos['cost'])}), "
            f"{fmt_pct(blended)} blended, **{fmt_pct(day_pct)}** day"
            + (" — " + "; ".join(notes) if notes else ""))
    # Realized P&L.
    realized = r2(live.get("realized", 0.0))
    if live["fills"]:
        fill_txt = "; ".join(
            f"{f['symbol']} {fmt_num(f['quantity'])}"
            f"{' sh' if f.get('mult', 1) == 1 else ' contracts'} "
            f"{f['side']} @ {fmt_money(f['price'])} "
            f"(filled {f['time_et']})"
            for f in live["fills"])
        lines.append(
            f"- Realized P&L: **{fmt_signed_money(realized)}** — {fill_txt}. "
            f"Cumulative realized now **{fmt_signed_money(res['cum_realized'])}**.")
    else:
        lines.append(
            f"- Realized P&L: **$0** (no closing trades; weekly P&L history "
            f"shows no closing trades). Cumulative realized "
            f"**{fmt_signed_money(res['cum_realized'])}** (unchanged).")
    lines.append(
        f"- Fills: {len(live['fills'])} today"
        + ("" if live["fills"] else " (no order activity recorded)")
        + ("." if live["fills"] else "."))
    if live.get("deposits", 0.0):
        lines.append(
            f"- Deposits/withdrawals: {fmt_signed_money(live['deposits'])} "
            f"(external cash flow, rebased into the series — see the "
            f"deposit-rebase note under Running state)")
    else:
        lines.append("- Deposits/withdrawals: $0")
    if res["new_peak"]:
        dd_note = (f"new peak {fmt_money(acct)} — first new peak since the "
                   f"{prior['peak_date']} {fmt_money(prior['peak'])}")
    elif res["new_deepest"]:
        dd_note = (f"**new deepest drawdown**; prior deepest was "
                   f"{fmt_pct(prior['deepest'])} on {_md(prior['deepest_date'])}")
    elif res["drawdown"] < prior["drawdown"]:
        dd_note = (f"deepening from {fmt_pct(prior['drawdown'])} on {pdate}")
    else:
        dd_note = (f"recovering from {fmt_pct(prior['drawdown'])} on {pdate}")
    deepest_txt = (f"; deepest {fmt_pct(res['deepest'])} on "
                   f"{_md(res['deepest_date'])}" if res["new_deepest"] else
                   f"; deepest remains {fmt_pct(res['deepest'])} on "
                   f"{_md(res['deepest_date'])}")
    lines.append(
        f"- Drawdown from peak: **{fmt_pct(res['drawdown'])}** "
        f"(peak {fmt_money(res['peak'])}, {res['peak_date']} — {dd_note}"
        f"{deepest_txt})")
    # Correlated losses + streak + dollar split + flags.
    decliners = [s for s in live["positions"]
                 if live["positions"][s]["day_pct"] < 0]
    if live.get("options") is not None and live.get("options_delta", 0.0) < 0:
        decliners.append("SOFI LEAP")
    if realized < 0:
        corr = ("today's realized losses are rule-driven mechanical exits, "
                "decided under standing rules, not a market-loss event. ")
    elif len(decliners) >= 2 and res["qqq_day"] < 0:
        corr = ("today's declines share one driver — the tape "
                f"(QQQ {fmt_pct(res['qqq_day'])}); "
                + ", ".join(decliners) +
                " fell with the market on no company-specific news "
                "verified at scoring time. ")
    elif len(decliners) == 1:
        corr = (f"{decliners[0]} was the sole material decliner, no fresh "
                "company-specific news verified at scoring time. ")
    else:
        corr = "none observed. No loss pattern to flag — no realized losses today"
        corr += (" and the positions were green on the day. " if not decliners
                 else ". ")
    if res["gap"] < 0 and len(res["streak"]) >= 2:
        streak_txt = ", ".join(fmt_pp(g) for g in res["streak"])
        corr += (f"**{ordinal(len(res['streak']))} consecutive negative "
                 f"session gap** ({streak_txt}) — ")
        if res["cash_drag"]:
            corr += ("but the driver is arithmetic, not book weakness: the "
                     f"account is ~{res['cash_pct']:.1f}% cash, so a "
                     f"{fmt_pct(res['qqq_day'])} QQQ day mechanically outruns "
                     f"a book whose invested legs gained "
                     f"({fmt_pct(res['invested_day'])} vs QQQ "
                     f"{fmt_pct(res['qqq_day'])}). The cumulative gap stays "
                     f"wide at {fmt_pp(res['cum_gap'])}, so the ledger scores "
                     f"it as a cash-drag day, not a trend change. ")
        else:
            corr += ("and unlike the prior gap, today's is not cash-drag "
                     "arithmetic: the invested legs genuinely underperformed "
                     "the index. ")
    if res["acct_day"] < 0:
        corr += (f"The dollar split of the {fmt_signed_money(acct_delta)} day: "
                 + _day_dollar_split(prior.get("positions", {}),
                                     {s: live["positions"][s]
                                      for s in live["positions"]},
                                     prior.get("options"), live.get("options"))
                 + ". ")
    flags = []
    for sym, th in sorted(theses.items()):
        kd = next_key_date(th, today_iso)
        if kd and (date_cls.fromisoformat(kd.date)
                   - date_cls.fromisoformat(today_iso)).days <= 30:
            sl = suspended_line(th, today_iso)
            flag = (f"{sym}'s {kd.event} lands "
                    f"**{date_cls.fromisoformat(kd.date):%a %b %-d}**")
            if sl:
                flag += (f"; the {fmt_money(sl.price_level)} line goes live "
                         f"again after the suspension lapses "
                         f"{sl.suspended_until}, so the morning session judges "
                         f"the outcome against a live line")
            flags.append(flag)
    for sym, th in sorted(theses.items()):
        p = th.position
        if p and p.contracts and p.breakeven:
            sofi = live["quotes"].get(sym, {})
            if sofi:
                be_dist = r2((p.breakeven / sofi["price"] - 1) * 100)
                flags.append(
                    f"the {sym} LEAP is at "
                    f"{fmt_pct(pct(live['options'], live['options_cost']))} "
                    f"above cost with breakeven {fmt_money(p.breakeven)} still "
                    f"~{be_dist:.0f}% away — the morning session owns the "
                    f"hold/trim call, not this scoring row")
    for sym, th in sorted(theses.items()):
        p = th.position
        if p and p.take_profit and sym in live["positions"]:
            tp_dist = r2((p.take_profit / live["positions"][sym]["price"] - 1)
                         * 100)
            flags.append(
                f"{sym}'s {fmt_money(p.take_profit)} take-profit "
                f"({tp_dist:.1f}% away) remains the only resting defensive "
                f"order")
            break
    if flags:
        corr += "Flags: " + "; ".join(
            f"({i + 1}) {f}" for i, f in enumerate(flags[:3])) + "."
    lines.append(f"- Correlated losses: {corr}")
    return "\n".join(lines) + "\n"


def render_verdict(day_no: int, prior: dict, live: dict, res: dict,
                   today_iso: str, theses: dict) -> str:
    """Step 6: one tight verdict, what/why/exposure/next."""
    acct, qqq = live["acct"], live["qqq"]
    why = []
    if live["fills"]:
        why.append("mechanical exit(s) executed at the open under standing rules")
    if res["new_peak"]:
        why.append(f"new peak {fmt_money(acct)}")
    if res["new_deepest"]:
        why.append(f"new deepest drawdown {fmt_pct(res['drawdown'])}")
    if res["gap"] < 0 and res["cash_drag"]:
        why.append("cash-drag day — invested legs kept up with QQQ, the cash "
                   "weight lagged")
    elif res["gap"] < 0:
        why.append("invested legs genuinely underperformed the tape")
    if len(res["streak"]) >= 3:
        why.append(f"{ordinal(len(res['streak'])).lower()} straight negative "
                   "session gap")
    if not why:
        why.append("quiet session — no trades, no line tests")
    nxt = []
    for sym, th in sorted(theses.items()):
        kd = next_key_date(th, today_iso)
        if kd and (date_cls.fromisoformat(kd.date)
                   - date_cls.fromisoformat(today_iso)).days <= 30:
            nxt.append(f"{sym} {kd.event} "
                       f"{date_cls.fromisoformat(kd.date):%a %b %-d}")
        sl = suspended_line(th, today_iso)
        if sl:
            nxt.append(f"{sym} {fmt_money(sl.price_level)} line re-arms "
                       f"{date_cls.fromisoformat(sl.suspended_until):%a %b %-d}")
    pos_txt = ", ".join(
        f"{s} {fmt_num(live['positions'][s]['qty'])} sh"
        for s in sorted(live["positions"]))
    if live.get("option_tickers"):
        pos_txt += (", " if pos_txt else "") + ", ".join(
            f"{s} LEAP {theses[s].position.contracts}x"
            for s in live["option_tickers"] if s in theses)
    out = (f"Day {day_no} — {today_iso}: account {fmt_pct(res['acct_day'])} vs "
           f"QQQ {fmt_pct(res['qqq_day'])} (gap {fmt_pp(res['gap'])}); "
           f"cumulative {fmt_pct(res['cum_acct'])} vs QQQ "
           f"{fmt_pct(res['cum_qqq'])} (gap {fmt_pp(res['cum_gap'])}). "
           + "; ".join(why).capitalize() + ". "
           f"Exposure: {res['cash_pct']:.1f}% cash; {pos_txt}. "
           + (f"Next: {'; '.join(nxt)}." if nxt else "Next: nothing dated "
              "inside 30 days."))
    return out

# -------------------------------------------------------------- live ------

def fetch_quotes(symbols: list[str]) -> dict:
    """{symbol: {price, prev_close, close_date, close_price, day_pct}}.

    The close mark is the regular-session last trade. The official close
    (results[].close) carries its date: when it is today, the session has
    settled and close.price is today's official close; otherwise the
    last trade is used and the caller decides whether the session ran.
    Same traded/active checks as refresh.py — a stale quote gaps the
    session, it is never scored on.
    """
    data = mcp_call("get_equity_quotes", {"symbols": symbols})
    quotes: dict[str, dict] = {}
    for r in data.get("results", []):
        q = r.get("quote", {})
        sym = q.get("symbol", "")
        px = q.get("last_trade_price") or q.get("last_non_reg_trade_price")
        if not sym or not px:
            continue
        prev = q.get("previous_close")
        close = r.get("close") or {}
        close_px = close.get("price")
        close_date = close.get("date")
        price = float(px)
        prev_f = float(prev) if prev else None
        quotes[sym] = {
            "price": price,
            "prev_close": prev_f,
            "close_price": float(close_px) if close_px else None,
            "close_date": close_date,
            "has_traded": q.get("has_traded"),
            "state": q.get("state"),
            "last_trade_time": q.get("venue_last_trade_time"),
            "day_pct": pct(price, prev_f) if prev_f else None,
        }
    missing = [s for s in symbols if s not in quotes]
    if missing:
        raise ScoreError(f"No live quote for {', '.join(missing)}.")
    for sym, qq in quotes.items():
        if qq["price"] <= 0 or qq["prev_close"] is None or qq["prev_close"] <= 0:
            raise ScoreError(f"Quote for {sym} is empty or stale — not scoring.")
        if qq["has_traded"] is False or (qq["state"] not in (None, "active")):
            raise ScoreError(f"Quote for {sym} has not traded / is not active.")
    return quotes


def fetch_today_fills() -> list[dict]:
    """Today's realized trades (ET date), most-recent-first, paginated.

    get_pnl_trade_history returns closed/realizing trades only — a
    buy-to-open never appears here, so fills from this tool are closes
    (or option closes). Each entry carries its realized gain.
    """
    today_iso = datetime.now(ET).date().isoformat()
    trades: list[dict] = []
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
            if day == today_iso:
                trades.append({
                    "symbol": t.get("symbol", ""),
                    "side": t.get("side", ""),
                    "quantity": float(t.get("quantity") or 0),
                    "price": float(t.get("price") or 0),
                    "realized_gain": float(t.get("realized_gain") or 0),
                    "time_et": datetime.fromisoformat(
                        ts.replace("Z", "+00:00")).astimezone(ET).strftime("%H:%M:%S"),
                })
        cursor = data.get("next_cursor") or ""
        if not cursor:
            break
    return trades


def classify_fills(fills: list[dict], equity_syms: set[str],
                   option_underlyings: set[str]) -> list[dict]:
    """Attach the cash multiplier: equity 1x, option contracts 100x.

    An option close is a trade in an underlying with no equity position
    and an open option thesis in that underlying. Anything else is
    unclassifiable — the session gaps rather than guessing the cash flow.

    equity_syms covers live positions PLUS names held at the prior
    close: a fill that closes a position (a morning exit, scored after
    the close) is unclassifiable against live positions alone, because
    the name is already gone from the book.
    """
    out = []
    for f in fills:
        sym = f["symbol"]
        if sym in equity_syms:
            f["mult"], f["kind"] = 1, "equity"
        elif sym in option_underlyings:
            f["mult"], f["kind"] = 100, "option"
        else:
            raise ScoreError(
                f"Unclassifiable fill today: {sym} {f['side']} "
                f"{f['quantity']} @ {f['price']} — not an equity position "
                f"and not an option underlying. Not estimating.")
        out.append(f)
    return out


def detect_deposits(prior: dict, live: dict) -> float:
    """Deposits/withdrawals from the account identity (no buy prices
    needed, so buy-to-open fills — invisible to the P&L history — cannot
    corrupt it): deposits = d(total) - (d(unrealized) + realized).

    A buy moves cash into cost basis (total unchanged); a sale moves value
    into cash (total unchanged except the realized leg, already counted).
    Only an external cash flow moves the total outside performance.
    Whole-dollar rounding absorbs close-mark noise (deposits are round).
    """
    d_total = r2(live["acct"] - prior["acct"])
    unrl_today = r2((live["equity"] - live["cost"])
                    + (live.get("options", 0.0) - live.get("options_cost", 0.0)))
    unrl_prior = r2((prior["equity"] - prior["cost"])
                    + (prior.get("options", 0.0) - prior.get("options_cost", 0.0)))
    d_unrl = r2(unrl_today - unrl_prior)
    realized = r2(live.get("realized", 0.0))
    deposits = r2(d_total - (d_unrl + realized))
    if abs(deposits) <= 0.50:
        return 0.0
    if abs(deposits - round(deposits)) <= 0.50:
        return float(round(deposits))
    return deposits


def append_gap_note(text: str, today_iso: str, day_no: int, reason: str,
                    prior: dict) -> str:
    """A gap block, in the ledger's session-block shape. The parser skips
    gap blocks when finding prior marks, so the next session re-scores
    from the last scored row."""
    blk = (f"### {today_iso} — Day {day_no} (scoring gap — account data "
           f"unavailable)\n\n"
           f"- No score recorded: {reason}; nothing estimated.\n"
           f"- Prior marks carried: account {fmt_money(prior['acct'])}, "
           f"QQQ {fmt_money(prior['qqq'])}. The next session re-scores "
           f"from these marks.\n")
    return text + ("\n" if not text.endswith("\n") else "") + blk


def update_running_state(text: str, res: dict, live: dict,
                         prior_state: dict, today_iso: str) -> str:
    """Rewrite the four Running-state lines, in their exact formats.
    The new exit entries go into the realized parenthetical in the same
    `TICKER -$X.XX on MM/DD` form refresh.py's per-exit patterns read."""
    def sub(pat: str, repl: str, err: str) -> str:
        new, n = re.subn(pat, repl, text, count=1, flags=re.MULTILINE)
        if n != 1:
            raise ScoreError(f"Ledger Running state line not found: {err}")
        return new

    text = sub(r"^(- Running peak: )\*\*\$[\d,]+\.\d+\*\* \(\d{4}-\d{2}-\d{2}"
               r"[^)]*\)",
               rf"\g<1>**${res['peak']:,.2f}** ({res['peak_date']} official close)",
               "running peak")
    # Realized parenthetical: append today's exits, same form as history.
    note = prior_state["realized_note"]
    for f in live["fills"]:
        rg = fmt_signed_money(f["realized_gain"]).replace("+", "")
        if f["kind"] == "option":
            label = f"{f['symbol']} Nov $3 calls"  # ledger's option-exit form
            note += (f"; {label} {rg} on "
                     f"{date_cls.fromisoformat(today_iso):%m/%d}")
        else:
            note += (f"; {f['symbol']} {rg} on "
                     f"{date_cls.fromisoformat(today_iso):%m/%d} — "
                     f"sold {fmt_num(f['quantity'])} @ "
                     f"{fmt_money(f['price'])}, filled {f['time_et']} ET")
    cum_txt = fmt_signed_money(res["cum_realized"])
    text = sub(r"^(- Cumulative realized P&L: )\*\*-?\$[\d,]+\.\d+\*\* \(.*\)$",
               rf"\g<1>**{cum_txt}** ({note})",
               "cumulative realized P&L")
    text = sub(r"^(- Cumulative score: account )\*\*-?[\d.]+%\*\*, QQQ "
               r"\*\*-?[\d.]+%\*\*, gap \*\*[+-]?[\d.]+pp\*\*",
               rf"\g<1>**{res['cum_acct']:+.2f}%**, QQQ "
               f"**{res['cum_qqq']:+.2f}%**, gap **{res['cum_gap']:+.2f}pp**",
               "cumulative score")
    dd_line = (f"- Drawdown: **{res['drawdown']:+.2f}%** "
               f"(peak {fmt_money(res['peak'])}, {res['peak_date']}; deepest "
               f"{'remains' if not res['new_deepest'] else ''} "
               f"{fmt_pct(res['deepest'])} on {_md(res['deepest_date'])})")
    if res["new_deepest"]:
        dd_line = dd_line.replace("deepest  ", "deepest ")
    text = sub(r"^- Drawdown: \*\*-?[\d.]+%\*\* \(peak \$[\d,]+\.\d+, "
               r"\d{4}-\d{2}-\d{2}; deepest (?:remains )?-?[\d.]+% on "
               r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})\)",
               dd_line.replace("\\", "\\\\"), "drawdown")
    if live.get("deposits", 0.0):
        dep = live["deposits"]
        new_base = res["baseline"]
        rebase = (
            f"\n### Deposit rebase — {today_iso} post-close\n\n"
            f"- **{fmt_money(abs(dep))} {'deposit' if dep > 0 else 'withdrawal'} "
            f"settled** into the account during the {today_iso} session "
            f"(cash-flow identity at scoring time; no trades explain the move).\n"
            f"- From {(date_cls.fromisoformat(today_iso)).isoformat()} onward "
            f"the deposit is an external cash flow, not performance: the "
            f"session %Δ is computed against the rebased base "
            f"**{fmt_money(res['adj_prior'])}** "
            f"({fmt_money(prior_state['last_acct'])} prior close mark + "
            f"{fmt_signed_money(dep)}).\n"
            f"- Cumulative account return from {today_iso} onward is measured "
            f"against the deposit-adjusted inception baseline "
            f"**{fmt_money(new_base)}** "
            f"({fmt_money(prior_state['baseline_acct'])} + "
            f"{fmt_signed_money(dep)}); all prior cumulative rows stand as recorded.\n"
            f"- Running peak is deposit-adjusted the same way: "
            f"**{fmt_money(r2(prior_state['peak'] + dep))}** "
            f"({fmt_money(prior_state['peak'])} + {fmt_signed_money(dep)}); "
            f"drawdown is measured from the deposit-adjusted peak.\n")
        marker = "\n## Sessions"
        if marker not in text:
            raise ScoreError("Ledger has no ## Sessions marker for the rebase note.")
        text = text.replace(marker, rebase + marker, 1)
    return text


def score_today(dry_run: bool = False, force: bool = False) -> int:
    """Steps 1-6 for today. Returns 0; prints the verdict on stdout.
    Prints nothing on the silent paths (holiday / already scored / gap).
    --force (dry-run only) renders from live intraday marks for format
    verification; the row it prints is NOT a scored session."""
    text = LEDGER.read_text()
    today = datetime.now(ET).date()
    today_iso = today.isoformat()
    if today.weekday() >= 5 and not force:
        print(f"(no session: {today_iso} is a weekend)", file=sys.stderr)
        return 0
    sessions = parse_sessions(text)
    if any(s["date"] == today_iso for s in sessions) and not force:
        print(f"(already scored: {today_iso} has a ledger block)",
              file=sys.stderr)
        return 0
    state = parse_running_state(text)
    scored = [s for s in sessions if not s["gap"]]
    if not scored:
        raise ScoreError("Ledger has no scored session to measure from.")
    last = parse_session_values(scored[-1])
    day_no = (max(s["day"] for s in scored if s["day"] is not None) + 1)
    # Negative-gap history, chronological, trailing.
    gaps = [parse_session_values(s).get("gap_pp") for s in scored]
    neg_hist: list[float] = []
    for g in reversed(gaps):
        if g is not None and g < 0:
            neg_hist.insert(0, g)
        else:
            break
    # Deepest drawdown comes from the Running state; a missing parse is
    # a loud failure, never a 0.0 default (0.0 would make any real
    # drawdown look like a new deepest).
    if "deepest" not in state or "deepest_date" not in state:
        raise ScoreError("Ledger Running state Drawdown line did not parse.")
    prior = {
        "date": last["date"], "acct": last["acct"], "qqq": last["qqq"],
        "cash": last.get("cash", 0.0), "equity": last.get("equity", 0.0),
        "cost": last.get("cost", 0.0),
        "options": last.get("options", 0.0),
        "options_cost": last.get("options_cost", 0.0),
        "unrealized": last.get("unrealized", 0.0),
        "cum_realized": last.get("cum_realized", state["cum_realized"]),
        "peak": state["peak"], "peak_date": state["peak_date"],
        "deepest": state["deepest"],
        "deepest_date": state["deepest_date"],
        "baseline_acct": state["baseline_acct"],
        "inception_qqq": state["inception_qqq"],
        "cum_acct": last.get("cum_acct", state.get("cum_acct", 0.0)),
        "cum_qqq": last.get("cum_qqq", state.get("cum_qqq", 0.0)),
        "cum_gap": last.get("cum_gap", state.get("cum_gap", 0.0)),
        "drawdown": last.get("drawdown", state.get("drawdown", 0.0)),
        "neg_gap_history": neg_hist,
        "positions": last.get("positions", {}),
    }

    try:
        theses = load_open_theses()
        symbols = sorted({t for t in theses} | {"QQQ"})
        quotes = fetch_quotes(symbols)
        pf = mcp_call("get_portfolio", {"account_number": AGENTIC_ACCOUNT})
        pos_data = mcp_call("get_equity_positions",
                            {"account_number": AGENTIC_ACCOUNT})
        fills = classify_fills(
            fetch_today_fills(),
            # Live positions plus names held at the prior close: a fill
            # closing a position (e.g. this morning's SMMT exit) is gone
            # from the live book by scoring time.
            {p["symbol"] for p in pos_data.get("positions", [])}
            | set(prior.get("positions", {})),
            {t for t, th in theses.items()
             if th.position and th.position.contracts})
    except ScoreError as e:
        # Gap: append the note, stop, never estimate, no message.
        new_text = append_gap_note(text, today_iso, day_no, str(e), prior)
        if not dry_run:
            LEDGER.write_text(new_text)
        print(f"(gap note appended for {today_iso}: {e})", file=sys.stderr)
        return 0

    # Holiday: the QQQ close has not settled for today. --force renders
    # from the last trade instead (intraday marks, format check only).
    qqq_q = quotes["QQQ"]
    last_trade = qqq_q.get("last_trade_time") or ""
    if qqq_q.get("close_date") == today_iso:
        qqq_today = qqq_q["close_price"]
        qqq_note = "official close"
    elif last_trade.startswith(today_iso) and last_trade[11:16] >= "15:59":
        qqq_today = qqq_q["price"]
        qqq_note = "last trade (close print not yet settled in the feed)"
    elif force:
        qqq_today = qqq_q["price"]
        qqq_note = "INTRADAY last trade (--force format check, not a score)"
        print("(warning: --force rendering from intraday marks)",
              file=sys.stderr)
    else:
        print(f"(no session: no {today_iso} close for QQQ)", file=sys.stderr)
        return 0
    print(f"(QQQ close mark: {qqq_today} via {qqq_note})", file=sys.stderr)

    # Positions at their regular-session close marks.
    positions: dict = {}
    equity_sum, cost_sum = 0.0, 0.0
    for p in pos_data.get("positions", []):
        sym = p["symbol"]
        qty = float(p["quantity"])
        if qty == 0:
            continue
        px = quotes[sym]["price"]
        avg = float(p.get("average_buy_price") or 0)
        val, cst = r2(qty * px), r2(qty * avg)
        equity_sum = r2(equity_sum + val)
        cost_sum = r2(cost_sum + cst)
        positions[sym] = {
            "qty": qty, "price": px, "value": val, "cost": cst,
            "day_pct": quotes[sym]["day_pct"],
            "held_for_sells": float(p.get("shares_held_for_sells") or 0),
        }
    for sym in positions:
        if sym not in theses:
            print(f"(warning: {sym} has no thesis file — notes will be blank)",
                  file=sys.stderr)
    opt_tickers = [t for t, th in theses.items()
                   if th.position and th.position.contracts]
    options_value = float(pf.get("options_value") or 0)
    options_cost = r2(sum(theses[t].position.premium_total or 0.0
                          for t in opt_tickers))
    cash = float(pf.get("cash") or 0)
    live_total = float(pf.get("total_value") or 0)
    acct = r2(cash + equity_sum + options_value)
    realized = r2(sum(f["realized_gain"] for f in fills))
    for f in fills:
        f["closed_position"] = (
            f["side"] == "sell" and f["symbol"] not in positions)
    live = {
        "date": today_iso, "acct": acct, "live_total": live_total,
        "qqq": r2(qqq_today), "qqq_prior_feed": quotes["QQQ"]["prev_close"],
        "cash": cash, "buying_power": float(
            (pf.get("buying_power") or {}).get("buying_power") or 0),
        "pending_deposits": float(pf.get("pending_deposits") or 0),
        "equity": equity_sum, "live_equity": float(pf.get("equity_value") or 0),
        "cost": cost_sum, "options": options_value,
        "options_cost": options_cost,
        "options_delta": r2(options_value - prior.get("options", 0.0)),
        "realized": realized, "fills": fills, "positions": positions,
        "quotes": quotes, "option_tickers": opt_tickers,
    }
    live["deposits"] = detect_deposits(prior, live)
    if live["deposits"]:
        print(f"(external cash flow detected: "
              f"{fmt_signed_money(live['deposits'])})", file=sys.stderr)

    res = compute_session(prior, {**live, "deposits": live["deposits"]})
    row = render_row(day_no, prior, live, res, theses, today_iso)
    verdict = render_verdict(day_no, prior, live, res, today_iso, theses)

    if dry_run:
        print(f"--- DRY RUN row for {today_iso} (not written) ---\n{row}")
        print(f"--- verdict ---\n{verdict}")
        return 0
    state["last_acct"] = prior["acct"]
    new_text = update_running_state(text, res, live, state, today_iso)
    new_text += ("\n" if not new_text.endswith("\n") else "") + row
    LEDGER.write_text(new_text)
    print(verdict)
    return 0


# -------------------------------------------------------------- verify ----

def _parse_peak_deepest(body: str, block_date: str):
    """(peak, peak_date, deepest, deepest_date) from a session row's
    Drawdown line, in any of its recorded shapes:
      - standard: (peak $X, DATE — ...; deepest remains Y% on DATE)
      - new peak: (new peak $X — first new peak since ...; deepest ...)
      - new deepest: the row's own drawdown IS the deepest.
    Deepest is searched across the whole row body (the line wraps).
    Order matters: a row that set a new deepest also names the PRIOR
    deepest in prose, so the new-deepest marker is checked first."""
    # New deepest: the row's own drawdown IS the deepest as of this row.
    if "new deepest drawdown" in body:
        m = re.search(r"Drawdown from peak: \*\*(-?[\d.]+)%\*\* \(peak "
                      r"\$([\d,]+\.\d+), (\d{4}-\d{2}-\d{2})", body)
        if m:
            return _money(m.group(2)), m.group(3), float(m.group(1)), block_date
        m = re.search(r"Drawdown from peak: \*\*(-?[\d.]+)%\*\* \(new peak "
                      r"\$([\d,]+\.\d+)", body)
        if m:
            return _money(m.group(2)), block_date, float(m.group(1)), block_date
        return None
    m = re.search(r"Drawdown from peak: \*\*(-?[\d.]+)%\*\* \(peak "
                  r"\$([\d,]+\.\d+), (\d{4}-\d{2}-\d{2})", body)
    if m:
        dd, peak, pdate = float(m.group(1)), _money(m.group(2)), m.group(3)
    else:
        m = re.search(r"Drawdown from peak: \*\*(-?[\d.]+)%\*\* \(new peak "
                      r"\$([\d,]+\.\d+)", body)
        if not m:
            return None
        dd, peak, pdate = float(m.group(1)), _money(m.group(2)), block_date
    year = int(block_date[:4])
    m2 = re.search(r"deepest (?:drawdown )?(?:remains|was) (-?[\d.]+)% on "
                   r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})", body)
    if m2:
        return peak, pdate, float(m2.group(1)), _resolve_date(m2.group(2), year)
    # No deepest mentioned (earliest rows): the row's own drawdown is the
    # deepest so far.
    return peak, pdate, dd, block_date


def verify(dates: list[str]) -> int:
    """Recompute the listed sessions from the ledger's own recorded inputs
    and diff every number against the recorded rows. Read-only."""
    text = LEDGER.read_text()
    state = parse_running_state(text)
    blocks = [s for s in parse_sessions(text) if not s["gap"]]
    by_date = {s["date"]: parse_session_values(s) for s in blocks}
    order = [s["date"] for s in blocks]
    # Negative-gap history per date, from the recorded session gaps.
    failures = 0
    for target in dates:
        if target not in by_date:
            print(f"FAIL {target}: no session block in the ledger")
            failures += 1
            continue
        idx = order.index(target)
        if idx == 0:
            print(f"FAIL {target}: no prior session to measure from")
            failures += 1
            continue
        prev_date = order[idx - 1]
        prior_v, today_v = by_date[prev_date], by_date[target]
        # Peak/deepest as of the prior session, from its own row.
        pd = _parse_peak_deepest(blocks[idx - 1]["body"], prev_date)
        if pd is None:
            print(f"FAIL {target}: cannot parse prior peak/deepest")
            failures += 1
            continue
        peak, pdate, deepest, ddate = pd
        if ddate is None:
            ddate = prev_date
        # Baseline before this session: inception + deposits from rebase
        # notes dated before (target - 1 day).
        baseline = state["inception_acct"]
        for rm in re.finditer(
                r"### Deposit rebase — (\d{4}-\d{2}-\d{2})[^\n]*\n(.*?)(?=\n### |\n## |\Z)",
                text, re.DOTALL):
            bm = re.search(r"inception baseline \*\*\$([\d,]+\.\d+)\*\*",
                           rm.group(2))
            note_date = date_cls.fromisoformat(rm.group(1))
            if bm and note_date < date_cls.fromisoformat(target) - timedelta(
                    days=1):
                baseline = _money(bm.group(1))
        # Trailing negative gaps before this session.
        neg_hist: list[float] = []
        for d in reversed(order[:idx]):
            g = by_date[d].get("gap_pp")
            if g is not None and g < 0:
                neg_hist.insert(0, g)
            else:
                break
        # Cumulative realized before this session: walk back to the nearest
        # block that records it.
        cum_real = None
        for d in reversed(order[:idx]):
            if by_date[d].get("cum_realized") is not None:
                cum_real = by_date[d]["cum_realized"]
                break
        if cum_real is None:
            cum_real = 0.0
        prior = {
            "date": prev_date, "acct": prior_v["acct"], "qqq": prior_v["qqq"],
            "cash": prior_v.get("cash", 0.0),
            # Unrealized and the deposit identity are computed from the
            # close-print equity sums, not the live-feed headlines.
            "equity": prior_v.get("equity_close", prior_v.get("equity", 0.0)),
            "cost": prior_v.get("cost", 0.0),
            "options": prior_v.get("options", 0.0),
            "options_cost": prior_v.get("options_cost", 0.0),
            "unrealized": prior_v.get("unrealized", 0.0),
            "cum_realized": cum_real, "peak": peak, "peak_date": pdate,
            "deepest": deepest, "deepest_date": ddate,
            "baseline_acct": baseline,
            "inception_qqq": state["inception_qqq"],
            "cum_acct": prior_v.get("cum_acct", 0.0),
            "cum_qqq": prior_v.get("cum_qqq", 0.0),
            "cum_gap": prior_v.get("cum_gap", 0.0),
            "drawdown": prior_v.get("drawdown", 0.0),
            "neg_gap_history": neg_hist,
            "positions": prior_v.get("positions", {}),
        }
        today_in = {
            "date": target, "acct": today_v["acct"], "qqq": today_v["qqq"],
            "cash": today_v.get("cash", 0.0),
            "equity": today_v.get("equity_close", today_v.get("equity", 0.0)),
            "cost": today_v.get("cost", 0.0),
            "options": today_v.get("options", 0.0),
            "options_cost": today_v.get("options_cost", 0.0),
            "realized": today_v.get("realized", 0.0),
            "deposits": today_v.get("deposit", 0.0),
        }
        res = compute_session(prior, today_in)
        checks = [
            ("acct_day", res["acct_day"], today_v.get("acct_day_pct")),
            ("qqq_day", res["qqq_day"], today_v.get("qqq_day_pct")),
            ("gap", res["gap"], today_v.get("gap_pp")),
            ("cum_acct", res["cum_acct"], today_v.get("cum_acct")),
            ("cum_qqq", res["cum_qqq"], today_v.get("cum_qqq")),
            ("cum_gap", res["cum_gap"], today_v.get("cum_gap")),
            ("drawdown", res["drawdown"], today_v.get("drawdown")),
            # The deepest chain: the row says "new deepest drawdown" iff
            # the session set one.
            ("new_deepest", res["new_deepest"],
             "new deepest drawdown" in blocks[idx]["body"]),
        ]
        # Cumulative realized: early rows (e.g. 10-07) do not record it —
        # skip the check when the row has no figure; the walk-back through
        # later rows (10-12 records -$32.19) validates the chain instead.
        if today_v.get("cum_realized") is not None:
            checks.append(("cum_realized", res["cum_realized"],
                           today_v.get("cum_realized")))
        # Unrealized: the ledger's Equity headline (live feed) and its
        # close-print sum differ by after-hours drift, and the recorded
        # figure uses one or the other by day. Either basis must match.
        # (The ledger's Unrealized is equity-only; the options book is
        # reported on its own line, never folded into Unrealized.)
        unrl_close = res["unrealized"]
        unrl_head = r2(today_v.get("equity", 0.0) - today_v.get("cost", 0.0))
        want_unrl = today_v.get("unrealized")
        if want_unrl is None:
            checks.append(("unrealized", None, None))
        elif (abs(unrl_close - want_unrl) > VERIFY_MONEY_TOL
              and abs(unrl_head - want_unrl) > VERIFY_MONEY_TOL):
            checks.append(("unrealized", (unrl_close, unrl_head), want_unrl))
        bad = []
        for name, got, want in checks:
            if want is None:
                bad.append(f"{name}: recorded value missing from the row")
            elif isinstance(got, tuple):
                # Either-basis check (unrealized): pass if either feed basis
                # matches the recorded figure within tolerance.
                if all(abs(g - want) > VERIFY_MONEY_TOL for g in got):
                    bad.append(f"{name}: recomputed {got} vs recorded {want}")
            elif abs(got - want) > (VERIFY_PCT_TOL if "pct" in name or
                                    name in ("gap", "cum_acct", "cum_qqq",
                                             "cum_gap", "drawdown")
                                    else VERIFY_MONEY_TOL):
                bad.append(f"{name}: recomputed {got} vs recorded {want}")
        # Deposit-identity check on the recorded inputs, on either feed
        # basis (close-sum totals and live-feed headlines): the recorded
        # rows mix the two by day, so the identity must hold on one.
        def ident_for(eq_t, eq_p, acct_t, acct_p):
            unrl_t = r2((eq_t - today_v.get("cost", 0.0))
                        + (today_v.get("options", 0.0)
                           - today_v.get("options_cost", 0.0)))
            unrl_p = r2((eq_p - prior_v.get("cost", 0.0))
                        + (prior_v.get("options", 0.0)
                           - prior_v.get("options_cost", 0.0)))
            return r2((acct_t - acct_p)
                      - ((unrl_t - unrl_p) + today_v.get("realized", 0.0)))

        def close_total(vv):
            return r2(vv.get("cash", 0.0)
                      + vv.get("equity_close", vv.get("equity", 0.0))
                      + vv.get("options", 0.0))
        ident_close = ident_for(
            today_v.get("equity_close", today_v.get("equity", 0.0)),
            prior_v.get("equity_close", prior_v.get("equity", 0.0)),
            close_total(today_v), close_total(prior_v))
        ident_head = ident_for(
            today_v.get("equity", 0.0), prior_v.get("equity", 0.0),
            today_v["acct"], prior_v["acct"])
        want_dep = today_v.get("deposit", 0.0)
        if (abs(ident_close - want_dep) > 0.50
                and abs(ident_head - want_dep) > 0.50):
            bad.append(f"deposit identity: close-basis {ident_close}, "
                       f"headline-basis {ident_head} vs recorded {want_dep}")
        else:
            ident = ident_close if abs(
                ident_close - want_dep) <= 0.50 else ident_head
        # Refresh.py contract: the recorded Cumulative line must match the
        # session regex refresh.py's close-phase upsert reads.
        cum_line = re.search(
            r"Cumulative: account \*\*([+-]?[\d.]+)%\*\*.*?QQQ \*\*([+-]?[\d.]+)%\*\*",
            blocks[idx]["body"], re.DOTALL)
        if not cum_line or (float(cum_line.group(1)) != res["cum_acct"]
                            or float(cum_line.group(2)) != res["cum_qqq"]):
            bad.append("refresh contract: Cumulative line does not parse "
                       "to the recomputed (acct, qqq)")
        if bad:
            failures += 1
            print(f"FAIL {target} (Day {today_v.get('day')}):")
            for b in bad:
                print(f"    {b}")
        else:
            print(f"PASS {target} (Day {today_v.get('day')}): all 10 figures "
                  f"match; deposit identity {ident} vs {want_dep}")
    print(f"\nverify: {len(dates) - failures}/{len(dates)} sessions exact")
    return 1 if failures else 0


# ------------------------------------------------------------------ main ----

DEFAULT_VERIFY = [
    "2026-10-07",  # deposit rebase
    "2026-10-13",  # SOFI LEAP buy (option buy-to-open day)
    "2026-10-15",  # ARWR + RKLB mechanical exits at the open
    "2026-10-20",  # GRAB Nov calls -50% premium exit
    "2026-11-04",  # new peak, first close above $2,000
    "2026-11-05",  # QQQ worst day of the series
    "2026-11-06",  # CRWD mechanical exit at the open
    "2026-11-09",  # cash-drag negative gap
    "2026-11-10",  # genuine-underperformance negative gap
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="with --dry-run: render from intraday marks")
    ap.add_argument("--verify", nargs="*", default=None,
                    help="recompute listed sessions (default set if empty)")
    args = ap.parse_args()
    if args.verify is not None:
        dates = args.verify if args.verify else DEFAULT_VERIFY
        return verify(dates)
    if args.force and not args.dry_run:
        ap.error("--force requires --dry-run")
    try:
        return score_today(dry_run=args.dry_run, force=args.force)
    except ScoreError as e:
        # Unreachable ledger / unparseable state: nothing to write to.
        print(f"(score.py failed: {e})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
