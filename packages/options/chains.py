"""Live option chains via the Robinhood MCP (broker quotes = truth).

Pipeline: get_option_chains (chain_id + expirations)
        -> get_option_instruments (contracts per chain)
        -> get_option_quotes (bid/ask/mark/IV per contract)

Read-only. Quotes are delayed when the market is closed; the module
labels them as such. If the MCP path fails, raises — the Yahoo options
fallback is a documented TODO, not a silent substitution (a bad quote
is worse than no quote for sizing decisions).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

MCP_PY = str(Path.home() / "workspace/robinhood-mcp/.venv/bin/python")
MCP_TOOL = str(Path.home() / "workspace/robinhood-mcp/mcp_tool.py")


def _mcp(tool: str, args: dict) -> dict:
    env = dict(os.environ, NO_PROXY="", no_proxy="")
    out = subprocess.run(
        [MCP_PY, MCP_TOOL, tool, json.dumps(args)],
        capture_output=True, text=True, timeout=90, env=env,
    )
    d = json.loads(out.stdout)
    if "error" in d:
        raise RuntimeError(f"{tool} failed: {d['error']}")
    return d["data"]


def _mcp_paged(tool: str, args: dict) -> list[dict]:
    """Follow the cursor until exhausted. get_option_instruments paginates
    (~100/page); reading only page 1 silently drops most of the chain —
    that exact bug killed the GRAB call analysis on 2026-10-07."""
    items, cursor, key = [], None, None
    for _ in range(50):
        a = dict(args)
        if cursor:
            a["cursor"] = cursor
        d = _mcp(tool, a)
        # find the list payload (key varies by tool)
        if key is None:
            key = next(k for k, v in d.items()
                       if isinstance(v, list) and v and isinstance(v[0], dict))
        items += d[key]
        cursor = d.get("next")
        if not cursor:
            break
    return items


def get_chain(ticker: str) -> dict:
    """Chain id + expiration dates for a ticker."""
    data = _mcp("get_option_chains", {"underlying_symbol": ticker})
    chains = [c for c in data["chains"] if c["symbol"] == ticker]
    if not chains:
        raise ValueError(f"no option chain for {ticker}")
    c = chains[0]
    return {"chain_id": c["id"], "expirations": c["expiration_dates"],
            "tradable": c.get("can_open_position", False)}


def get_contracts(chain_id: str, expiry: str | None = None,
                  kind: str | None = None) -> list[dict]:
    """Contracts, optionally filtered by expiry and kind (call/put).

    Paginates the full instrument list — the chain is ~300 contracts and
    the API returns ~100 per page.
    """
    instruments = _mcp_paged("get_option_instruments", {"chain_id": chain_id})
    out = []
    for i in instruments:
        if i.get("state") != "active" or i.get("tradability") != "tradable":
            continue
        if expiry and i["expiration_date"] != expiry:
            continue
        if kind and i["type"] != kind:
            continue
        out.append({"id": i["id"], "kind": i["type"],
                    "strike": float(i["strike_price"]),
                    "expiration": i["expiration_date"]})
    return sorted(out, key=lambda c: c["strike"])


def get_quotes(instrument_ids: list[str]) -> dict[str, dict]:
    """Bid/ask/mark/IV per contract id."""
    if not instrument_ids:
        return {}
    data = _mcp("get_option_quotes", {"instrument_ids": instrument_ids})
    quotes = {}
    for r in data["results"]:
        q = r.get("quote", r)
        iid = q.get("instrument_id", r.get("instrument_id"))
        quotes[iid] = {
            "bid": float(q["bid_price"]) if q.get("bid_price") else None,
            "ask": float(q["ask_price"]) if q.get("ask_price") else None,
            "mark": float(q.get("mark_price") or q.get("adjusted_mark_price") or 0) or None,
            "iv": float(q["implied_volatility"]) if q.get("implied_volatility") else None,
            "breakeven": float(q["breakeven_price"]) if q.get("breakeven_price") else None,
            "volume": int(q["volume"]) if q.get("volume") else 0,
            "open_interest": int(q["open_interest"]) if q.get("open_interest") else 0,
        }
    return quotes


def chain_snapshot(ticker: str, expiry: str, kind: str = "call") -> list[dict]:
    """Contracts + live quotes for one expiry/kind, sorted by strike."""
    chain = get_chain(ticker)
    if expiry not in chain["expirations"]:
        raise ValueError(f"{expiry} not in {ticker} expirations: "
                         f"{chain['expirations'][:6]}…")
    contracts = get_contracts(chain["chain_id"], expiry, kind)
    quotes = get_quotes([c["id"] for c in contracts])
    for c in contracts:
        c["quote"] = quotes.get(c["id"], {})
    return contracts
