"""SQLite TTL cache for market-data fetchers (stdlib only).

Every fetcher in this repo goes through `cached(key, ttl_s, fetch_fn)`:
fresh rows are served from ~/.cache/muse-trading/bars.db, stale or
missing rows trigger exactly one fetch. Keys are namespaced by
(symbol, interval, range) so daily and intraday never collide.

Rationale: without this, every check.py / dashboard / analytics run
re-hits Yahoo for the same six names. A 15-minute TTL means a full
morning session costs ~6 requests instead of ~60.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

CACHE_DIR = Path.home() / ".cache" / "muse-trading"
DB = CACHE_DIR / "bars.db"


def _conn() -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS bars (
        key TEXT PRIMARY KEY, fetched_at REAL, payload TEXT)""")
    return c


def cached(key: str, ttl_s: int, fetch_fn: Callable[[], object]) -> object:
    """Return cached payload if younger than ttl_s, else fetch + store."""
    c = _conn()
    try:
        row = c.execute(
            "SELECT fetched_at, payload FROM bars WHERE key=?", (key,)
        ).fetchone()
        if row and time.time() - row[0] < ttl_s:
            return json.loads(row[1])
    finally:
        c.close()
    payload = fetch_fn()
    c = _conn()
    try:
        c.execute(
            "INSERT OR REPLACE INTO bars VALUES (?, ?, ?)",
            (key, time.time(), json.dumps(payload)),
        )
        c.commit()
    finally:
        c.close()
    return payload


def invalidate(key: str) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM bars WHERE key=?", (key,))
        c.commit()
    finally:
        c.close()


def stats() -> dict:
    c = _conn()
    try:
        n, oldest = c.execute(
            "SELECT COUNT(*), MIN(fetched_at) FROM bars").fetchone()
        return {"rows": n, "oldest_age_s": time.time() - oldest if oldest else None}
    finally:
        c.close()
