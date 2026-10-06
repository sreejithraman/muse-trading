# apps/dashboard — book dashboard

The trading-desk view. Streamlit + TradingView lightweight-charts.

## Run

```bash
~/workspace/trading-tools/.venv/bin/streamlit run apps/dashboard/app.py
```

## What it shows

- **Positions table** — every holding: thesis status pill, live price,
  vs-cost %, stop distance %, the 3×ATR volatility stop next to the
  book's fixed stop, RS vs QQQ (20d), next catalyst, red-line flags
- **One tab per holding** — candlestick chart with stop + red-line
  price levels drawn on, claim, KPIs, recent evidence, key dates,
  decision log
- **Sidebar** — QQQ (the benchmark for the whole operation)

## Data & privacy

Runs locally against your **local** `packages/thesis/theses/` —
real positions, costs, stops. None of that is pushed: the public repo
ships only the fictional `EXAMPLE.yaml`, and the dashboard tells you
how to start your own book from it. Prices come from
`packages/data` (Yahoo v8); thesis state from `packages/thesis`;
volatility math from `packages/ta`.

## Dependencies

streamlit, streamlit-lightweight-charts (both pip-installable).
The 15-minute cache (`st.cache_data(ttl=900)`) keeps Yahoo happy.
