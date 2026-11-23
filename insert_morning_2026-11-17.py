import yaml
from pathlib import Path

base = Path.home() / "workspace/trading-tools/packages/thesis/theses"

grab_entry = """- date: '2026-11-17'
  text: >
    Morning session 2026-11-17: GRAB $3.21 (+6.0% vs $3.03 blended cost), +23.5% above the $2.60 close-based line -- far outside the 5% near-tripwire band, no checklist required. News scan: no thesis-breakers; Q3 beat-and-raise recaps continue (revenue $1.11B +27%, EBITDA $237M, FY26 guide $790-800M); Atome terms unchanged (60% for $1.49B, phase 1 close Q3 2027); stale "earnings Nov 17" aggregator templates are Q3-2026 confusion (already printed Nov 2). Native TP sell 33 sh @ $3.88 limit gtc resting (+20.9% away), state confirmed (order 6acfcf81). Account $1,796.00; 0 orders created today; no trades. TA: fixed $2.60 below 3xATR $2.81 (ATR 4.1%, high regime); RS vs QQQ +20.4%; RVOL 0.05 (quiet). Hold.
  source: morning session 2026-11-17
"""

sofi_entry = """- date: '2026-11-17'
  text: >
    Morning session 2026-11-17: SOFI $14.77 (-23.4% vs $19.28 LEAP breakeven). LEAP (Jan 2028 $15 call @ $4.30) marked $3.83 (-10.9% premium, options book $383 vs $430 cost); -50% premium exit $2.15 far; premium-double TP $8.60 far; breakeven $19.28 (+30.5% away); $13.50 re-eval line 9.4% below the stock, outside the 5% near-tripwire band. News scan: no thesis-breakers; Anthropic IPO pricing Wed Nov 18, first trade Thu Nov 19 -- SoFi one of six retail distributors for up to 20% to retail at IPO price, market has not paid for it (stock $15.42 Fri close, -4.9% last week); retail-sales control group +0.6% vs +0.3% expected and import prices +1.1% vs +0.7% are hot-tape macro, not a company event; NVDA earnings after close today is QQQ backdrop only. 0 orders created today; no trades. Hold.
  source: morning session 2026-11-17
"""

for name, entry in (("GRAB.yaml", grab_entry), ("SOFI.yaml", sofi_entry)):
    p = base / name
    text = p.read_text()
    assert "confirmation:" in text
    text = text.replace("confirmation:", entry + "confirmation:", 1)
    p.write_text(text)
    yaml.safe_load(p.read_text())
    print(name, "ok — decision entry inserted, YAML valid")
