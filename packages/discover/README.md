# discover — idea discovery pipeline

## x_pulse.py (2026-10-07)
Daily X digest via the Grok CLI on the user's X Premium+ subscription
(OAuth device flow — no xAI API key needed). Three headless queries
(flow / catalysts / news) over 15 vetted handles from the idea-discovery
research; writes a dated markdown digest for the morning session.

Verified: x_search works through the subscription proxy — real posts with
timestamps and links. Each run bills against the subscription quota.

Planned: Form 4 cluster-buy scanner (EDGAR), catalyst calendar sweep.
Cadence: X pulse + Form 4 daily pre-market (~8:30 AM), catalysts weekly.
