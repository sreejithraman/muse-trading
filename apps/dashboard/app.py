"""Mu$e book dashboard — Streamlit.

The trading desk view: every holding's thesis status, live price vs cost
and stops, ATR-based stop comparison, and annotated candlestick charts.

Runs locally: `~/workspace/trading-tools/.venv/bin/streamlit run
apps/dashboard/app.py`. Reads the *local* thesis YAMLs (private
positions — never pushed; the public repo ships only EXAMPLE.yaml).

Layout:
  - Book table: status pills, price, vs-cost, stop distance, ATR stop,
    next key date, red-line flags
  - One tab per holding: candlestick chart with stop + red-line levels,
    claim, KPIs, recent evidence, key dates, decision log
  - Sidebar: QQQ context + RS vs QQQ per holding
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "thesis"))
sys.path.insert(0, str(ROOT / "packages" / "ta"))
sys.path.insert(0, str(ROOT / "packages" / "data"))

from bars import fetch_daily  # noqa: E402
from models import Thesis, load_all  # noqa: E402
from signals import atr_stop, rs_vs_benchmark  # noqa: E402

st.set_page_config(page_title="Mu$e — Book", layout="wide")

STATUS_COLOR = {"INTACT": "green", "WEAKENED": "orange",
                "BROKEN": "red", "CLOSED": "gray"}


@st.cache_data(ttl=900)
def bars(symbol: str):
    return fetch_daily(symbol)


@st.cache_data(ttl=900)
def qqq_bars():
    return fetch_daily("QQQ")


def pill(status: str) -> str:
    color = STATUS_COLOR.get(status, "blue")
    return f":{color}[{status}]"


def book_table(theses, quotes, qqq):
    rows = []
    for t in theses:
        b = bars(t.ticker)
        px = b[-1]["close"] if b else None
        pos = t.position
        vs_cost = (px / pos.blended_cost - 1) * 100 if px and pos and pos.blended_cost else None
        stop_d = (px / pos.stop - 1) * 100 if px and pos and pos.stop else None
        s = atr_stop(b) if b else None
        rs = rs_vs_benchmark(b, qqq) if b and qqq else None
        today = date.today().isoformat()
        upcoming = sorted((k for k in t.key_dates if k.date >= today), key=lambda k: k.date)
        nxt = f"{upcoming[0].date} {upcoming[0].event[:30]}" if upcoming else "—"
        flags = []
        if px and pos and pos.stop:
            for rl in t.red_lines:
                if rl.price_level:
                    dist = (px / rl.price_level - 1) * 100
                    if 0 <= dist <= 5:
                        flags.append(f"⚠ {dist:.1f}% above ${rl.price_level:g}")
                    elif dist < 0:
                        flags.append(f"✖ below ${rl.price_level:g}")
        rows.append({
            "Ticker": t.ticker, "Thesis": t.status,
            "Price": round(px, 2) if px else None,
            "vs Cost %": round(vs_cost, 1) if vs_cost is not None else None,
            "Stop dist %": round(stop_d, 1) if stop_d is not None else None,
            "3×ATR stop": s["stop"] if s else None,
            "RS vs QQQ 20d %": rs,
            "Next catalyst": nxt, "Flags": "; ".join(flags),
        })
    return rows


def holding_tab(t: Thesis, qqq):
    b = bars(t.ticker)
    if not b:
        st.warning(f"No price data for {t.ticker}")
        return
    from streamlit_lightweight_charts import renderLightweightCharts

    candles = [{"time": x["date"], "open": x["open"], "high": x["high"],
                "low": x["low"], "close": x["close"]} for x in b]
    markers = []
    for rl in t.red_lines:
        if rl.price_level:
            markers.append({"price": rl.price_level,
                            "title": f"red line ${rl.price_level:g}"})
    if t.position and t.position.stop:
        markers.append({"price": t.position.stop,
                        "title": f"stop ${t.position.stop:g}"})
    price_lines = [{"price": m["price"], "color": "#ff4444",
                    "lineWidth": 1, "lineStyle": 2,
                    "axisLabelVisible": True, "title": m["title"]}
                   for m in markers]
    renderLightweightCharts([{
        "chart": {"layout": {"background": {"color": "#0e1117"},
                             "textColor": "#d3d3d3"},
                  "grid": {"vertLines": {"color": "rgba(42,46,57,0.5)"},
                           "horzLines": {"color": "rgba(42,46,57,0.5)"}}},
        "series": [{"type": "Candlestick", "data": candles,
                    "priceLines": price_lines,
                    "priceFormat": {"type": "price", "precision": 2,
                                    "minMove": 0.01}}],
    }], key=f"chart-{t.ticker}")

    st.markdown(f"**Claim.** {t.claim.strip()}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**KPIs**")
        for k in t.kpis:
            st.markdown(f"- {k['metric']}: target *{k['target']}*, now *{k['current']}*")
        st.markdown("**Key dates**")
        for k in t.key_dates:
            st.markdown(f"- {k.date}: {k.event}")
    with c2:
        st.markdown("**Recent evidence**")
        for e in t.evidence[-4:]:
            icon = "✅" if e.side == "for" else "🚩"
            st.markdown(f"- {icon} *{e.date}* — {e.text[:160]}")
        st.markdown("**Decisions**")
        for d in t.decisions[-3:]:
            st.markdown(f"- *{d.date}* — {d.text[:160]}")


def main():
    st.title("Mu$e — Book")
    theses = load_all()
    if not theses:
        st.info("No theses found. Copy `theses/EXAMPLE.yaml` to `<TICKER>.yaml` "
                "to start (real theses stay local, never pushed).")
        return
    qqq = qqq_bars()
    qqq_px = qqq[-1]["close"] if qqq else None
    qqq_chg = ((qqq[-1]["close"] / qqq[-2]["close"] - 1) * 100
               if qqq and len(qqq) > 1 else None)

    with st.sidebar:
        st.header("Market")
        if qqq_px:
            st.metric("QQQ", f"${qqq_px:,.2f}",
                      f"{qqq_chg:+.2f}%" if qqq_chg is not None else None)
        st.caption("Benchmark for the whole operation.")

    st.subheader("Positions")
    rows = book_table(theses, {}, qqq)
    st.dataframe(
        [{**r, "Thesis": pill(r["Thesis"])} for r in rows],
        width="stretch", hide_index=True,
    )

    st.subheader("Holdings")
    tabs = st.tabs([t.ticker for t in theses])
    for tab, t in zip(tabs, theses):
        with tab:
            holding_tab(t, qqq)


if __name__ == "__main__":
    main()
