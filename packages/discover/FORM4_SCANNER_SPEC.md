# Form 4 cluster-buy scanner — build spec

Goal: daily pre-market (~8:30 AM ET) scan for insider cluster buys, feeding the
9:40 morning session. Output: dated markdown digest like `x_pulse.py`.
Status: v1 BUILT 2026-10-07 (`form4_scanner.py`) — OpenInsider scrape, no key.
Deviations from spec: digests go to
`~/workspace/goals/agentic-account-trading-operation/hidden_files/form4-scan-YYYY-MM-DD.md`
(same dir the 9:40 session reads the x-pulse digests from), not
`packages/discover/digests/`. Universe = OpenInsider's own top-100 cluster
page (no separate watchlist needed for v1). Finnhub-keyed design shelved
unless the scrape breaks twice.

## Environment constraints (verified 2026-10-07, do not re-verify blindly)

- `www.sec.gov` (daily index, filing documents, ownership XML) returns **403
  from this egress IP regardless of User-Agent** — including SEC's documented
  contact-info UA format. The naive design (daily `form.YYYYMMDD.idx` + parse
  each filing's `ownership.xml`) is **dead here**.
- `data.sec.gov/submissions/CIK{10-digit}.json` **works** — per-company filing
  metadata (form, filingDate, accessionNumber, primaryDocument). Good for a
  per-holding insider monitor (our 7 names), not universe discovery.
- `efts.sec.gov/LATEST/search-index` **works** — full-text filing search.
  Verified: `?q="Form+4"&dateRange=custom&startdt=...&enddt=...&forms=4`
  returned 273 Form 4 hits for 2026-10-06→07 with CIKs + accession numbers
  (`adsh`). But hits carry **no transaction details** (no buy/sell, no $ size),
  so efts alone cannot detect clusters.

## Recommended v1 design

Two candidate data sources; pick one (needs Sreejith for the key in option 1):

1. **Finnhub `/stock/insider-transactions`** (preferred): transactionCode,
   shares, price, filingDate per symbol. Free tier likely sufficient. Needs a
   free API key signup (no key in env as of 2026-10-07). Run over a defined
   universe: holdings + screener shortlist + momentum watchlist (per-symbol
   endpoint — no universe scan). Cluster = 2+ distinct insiders with code `P`
   (open-market buy) within 5 trading days, or single buy > $1M.
2. **OpenInsider scrape via browser** (no key): openinsider.com publishes
   "latest cluster buys" screens as plain HTML. Fragile to site changes; fine
   as v1, revisit if it breaks twice.

Do NOT build on `www.sec.gov` document fetch. If the browser egress turns out
to reach sec.gov (unverified), efts-discovered accessions could be resolved
to XML that way — verify before designing around it.

## Output contract (for the 9:40 session)

- Dated markdown digest under `packages/discover/digests/`.
- Per cluster: issuer, ticker, insiders (name, title, $ size each), total $,
  transaction dates, filing links, one-line "why it might matter".
- Rank by total $ and insider count. Skip: option exercises (code M), 10b5-1
  planned sales, gifts. Flag explicitly when the insider signal is mixed
  (e.g. concurrent sales, as with GRAB's Ong Chin Yin 2026-10-05).
- Keep Sreejith's standing rule: insider buying is a **signal, not a price
  target** — report the cluster, not entry-precision commentary.

## Open decisions for the build session

- Finnhub key (ask Sreejith) vs OpenInsider scrape (no key, fragile).
- Universe list source: reuse `packages/screen` output or a static watchlist.
