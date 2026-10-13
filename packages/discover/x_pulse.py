"""X pulse: daily digest of trader posts via Grok subscription auth.

Uses the grok CLI (subscription OAuth, no API key) in headless single-turn
mode. The x_search tool is exposed through the subscription proxy —
verified 2026-10-07: real posts with timestamps and links returned.

Runs 4 queries (flow / catalysts / news / trending) over vetted handles from
the idea-discovery research, plus an open-ended trending sweep. Output:
markdown digest the morning session reads. Each query bills against the
user's Grok subscription quota, not API credits.

Handle curation is owned by Mu$e (standing direction 2026-10-12): nominate
promising accounts to CANDIDATES as they surface (flagged posts, trending
sweep, own research); promote to vetted on sustained rule-ins over ~2-4
weeks; cut vetted handles that go stale or noisy. Changes reported, not
asked.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

GROK = str(Path.home() / ".grok/bin/grok")

# Vetted handles from the idea-discovery research (2026-10-07)
HANDLES = {
    "flow": ["unusual_whales", "CheddarFlow", "BullflowIO", "itsCblast",
             "OptionsHawk", "snorlax_uw"],
    "catalysts": ["BPharmCatalyst", "SheffStation", "eWhispers",
                  "eliant_capital"],
    "news": ["FirstSquawk", "LiveSquawk", "Stocktwits", "QuiverQuant"],
}

# Candidate handles under evaluation (nominated from posts Sreejith flags).
# Candidates ride along in their section's scope at no extra query cost.
# Promotion to vetted needs a sustained hit rate over ~2-4 weeks — the morning
# session notes which candidates produce rule-ins; drop if noise.
CANDIDATES = {
    "catalysts": [
        # @JasonL_Capital — nominated 2026-10-12: structured SOFI LEAP writeup,
        # numbers verified against live sources, honest max-loss framing.
        "JasonL_Capital",
        # @FunOfInvesting — nominated 2026-10-13: META earnings setup (Truist
        # $1,000 raise + confirmed ~$10B Q3 legal charge not in prior expense
        # guidance) — numbers-heavy, checkable, catalyst-dated.
        "FunOfInvesting",
    ],
}

QUERIES = {
    "flow": ("Unusual options flow alerts in the last 24 hours: notable "
             "large/sweep call or put buying, tickers, strikes, expiries, "
             "and premium size. List the 5 most significant with post links."),
    "catalysts": ("Biotech FDA/PDUFA catalysts, earnings setups, or event-driven "
                  "trade ideas posted in the last 24 hours. List the 5 most "
                  "significant with tickers, dates, and post links."),
    "news": ("Breaking market-moving headlines in the last 24 hours: "
             "single-stock news, macro, unusual insider buying posts. "
             "List the 5 most significant with post links."),
    # Open-ended sweep beyond the vetted panel (added 2026-10-11): catches
    # crowded trades / viral DD the handle list misses. Substance filter in
    # the prompt keeps meme/pump chatter out; the morning session still vets
    # everything against the entry bar before it becomes an idea.
    "trending": ("The most-discussed tickers and trading topics on X in the "
                 "last 24 hours: unusual retail or institutional attention, "
                 "viral due-diligence threads, crowded trades forming. "
                 "Substance filter: skip pure meme/pump chatter with no news "
                 "hook, unusual volume, or verifiable catalyst. "
                 "List the 5 most significant with tickers, why each is "
                 "trending, and post links."),
}


def pulse(section: str, timeout_s: int = 180) -> tuple[str, dict]:
    """Run one headless Grok query. Returns (text, usage dict)."""
    handles = HANDLES.get(section, []) + CANDIDATES.get(section, [])
    scope = (f"posts from these accounts in the last 24 hours: "
             f"{' '.join(f'@{h}' for h in handles)}" if handles else
             "posts across trading/finance X in the last 24 hours")
    prompt = (f"Search X for {scope}. {QUERIES[section]} "
              f"Begin your response directly with the markdown list of results. "
              f"No preamble, no explanation of your search process.")
    out = subprocess.run(
        # --yolo: headless runs cancel web_fetch approvals otherwise, which
        # starves the agent of post contents (flow accounts post images) and
        # leaves only narration in the result. Always-approve is the documented
        # mode for scripts/agent servers; the prompt keeps the task narrow.
        [GROK, "--yolo", "--output-format", "json", "-p", prompt],
        capture_output=True, text=True, timeout=timeout_s)
    if out.returncode != 0:
        raise RuntimeError(f"grok -p failed: {out.stderr[:300]}")
    try:
        data = json.loads(out.stdout)
        return (data.get("text") or "").strip(), data.get("usage") or {}
    except (json.JSONDecodeError, AttributeError):
        return out.stdout.strip(), {}


def digest(out_dir: str | Path | None = None) -> Path:
    """Run all four pulses, write dated markdown digest. Returns path."""
    out_dir = Path(out_dir or Path.home() / "workspace/goals/"
                   "agentic-account-trading-operation/hidden_files")
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = out_dir / f"x-pulse-{today}.md"
    parts = [f"# X pulse — {today}", ""]
    usage_log: dict = {}
    for section in ("flow", "catalysts", "news", "trending"):
        try:
            # flow scans 6 handles and fetches post contents; catalysts and
            # the open-ended trending sweep are also heavy
            body, usage = pulse(section, timeout_s=300 if section in ("flow", "catalysts", "trending") else 180)
            usage_log[section] = {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_cost_usd": usage.get("total_cost_usd"),
            }
        except Exception as e:  # noqa: BLE001 — one failed pulse shouldn't kill the digest
            body = f"_pulse failed: {e}_"
            usage_log[section] = {"error": str(e)[:120]}
        parts += [f"## {section}", "", body, ""]
    path.write_text("\n".join(parts))
    # Quota burn log (private — lives next to the digests, never synced to
    # the public repo): one JSON line per run so we can watch subscription
    # usage as sections are added.
    try:
        with open(out_dir / "x-pulse-usage.jsonl", "a") as f:
            f.write(json.dumps({"date": today, "usage": usage_log}) + "\n")
    except Exception:
        pass
    return path


if __name__ == "__main__":
    p = digest()
    print(f"wrote {p}")
