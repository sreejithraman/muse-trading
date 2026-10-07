# discover — idea discovery pipeline

## x_pulse.py (2026-10-07)
Daily X digest via the Grok CLI on the user's X Premium+ subscription
(OAuth device flow — no xAI API key needed). Three headless queries
(flow / catalysts / news) over 15 vetted handles from the idea-discovery
research; writes a dated markdown digest for the morning session.

Verified: x_search works through the subscription proxy — real posts with
timestamps and links. Each run bills against the subscription quota.

## form4_scanner.py (2026-10-07)
Daily pre-market Form 4 cluster-buy scan via openinsider.com (plain HTML,
no API key — SEC's own endpoints 403 from this egress). Parses the latest
cluster-buys page, ranks top 12 purchase clusters by $ value, pulls
per-insider detail (name, title, $ size, SEC filing link) from ticker pages,
and flags mixed signals (same-window insider sales). Writes a dated digest
for the morning session. Run: `/usr/bin/python3
~/workspace/trading-tools/packages/discover/form4_scanner.py`.

Planned: catalyst calendar sweep.
Cadence: X pulse + Form 4 daily pre-market (~8:30 AM), catalysts weekly.
