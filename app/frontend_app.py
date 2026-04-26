from __future__ import annotations

from datetime import datetime

import streamlit as st

from app.main import (
    execution_planner,
    fetch_most_active_symbols,
    fetch_quotes,
    market_analyst,
    risk_manager,
)
from app.sentiment import get_news_sentiment


st.set_page_config(page_title="Trading Intelligence App", layout="wide")

st.title("📈 Trading Intelligence App")
st.caption("Day-trading signals + long-term ranking + market news sentiment")

with st.sidebar:
    st.header("Scanner settings")
    top_count = st.slider("Top picks", min_value=3, max_value=20, value=10)
    min_price = st.number_input("Min price", min_value=1.0, value=5.0, step=1.0)
    min_market_cap = st.number_input("Min market cap", min_value=0.0, value=2_000_000_000.0, step=500_000_000.0)
    min_rel_volume = st.slider("Min relative volume", min_value=0.5, max_value=3.0, value=1.1, step=0.1)
    max_spread_pct = st.slider("Max spread %", min_value=0.1, max_value=3.0, value=1.0, step=0.1)
    run_button = st.button("Run Scan", type="primary")



def _long_term_rank(quotes: list[dict]) -> list[dict]:
    ranked: list[dict] = []
    for q in quotes:
        symbol = q.get("symbol", "")
        name = q.get("shortName", "Unknown")
        price = float(q.get("regularMarketPrice", 0) or 0)
        market_cap = float(q.get("marketCap", 0) or 0)
        pe = float(q.get("trailingPE", 0) or 0)
        change_pct = float(q.get("regularMarketChangePercent", 0) or 0)

        quality = (market_cap / 1_000_000_000_000) * 8
        valuation = 8 if 0 < pe < 30 else 2
        trend = max(min(change_pct, 10), -10) + 10
        score = quality + valuation + trend

        ranked.append(
            {
                "Symbol": symbol,
                "Name": name,
                "Price": round(price, 2),
                "Market Cap": f"${market_cap/1_000_000_000:.1f}B",
                "P/E": round(pe, 2) if pe else None,
                "1D %": round(change_pct, 2),
                "Long-Term Score": round(score, 2),
            }
        )

    ranked.sort(key=lambda x: x["Long-Term Score"], reverse=True)
    return ranked


if run_button:
    with st.spinner("Running market scan..."):
        symbols = fetch_most_active_symbols(top_count)
        quotes = fetch_quotes(symbols)

        analysis = market_analyst(
            quotes=quotes,
            min_price=min_price,
            min_market_cap=min_market_cap,
        )

        quote_map = {q.get("symbol", ""): q for q in quotes}
        approved = risk_manager(
            market_analysis=analysis,
            quote_map=quote_map,
            min_rel_volume=min_rel_volume,
            max_spread_pct=max_spread_pct,
        )
        plans = execution_planner(approved, top_count)

        sentiment = get_news_sentiment([p.symbol for p in plans])
        long_term = _long_term_rank(quotes)[:top_count]

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Day Trading", "Long-Term", "Sentiment & News", "Automation"]
    )

    with tab1:
        st.subheader("Day-trading execution plan")
        st.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        rows = []
        for p in plans:
            sent = sentiment["symbol_scores"].get(p.symbol, 0.0)
            rows.append(
                {
                    "Symbol": p.symbol,
                    "Name": p.name,
                    "Entry": round(p.entry, 2),
                    "Stop": round(p.stop_loss, 2),
                    "Target": round(p.take_profit, 2),
                    "Conviction": round(p.conviction_score, 2),
                    "News Sentiment": round(sent, 2),
                    "Rationale": p.rationale,
                }
            )
        st.dataframe(rows, use_container_width=True)

    with tab2:
        st.subheader("Long-term watchlist ranking")
        st.caption("Blend of size/quality, valuation proxy, and short-term trend.")
        st.dataframe(long_term, use_container_width=True)

    with tab3:
        st.subheader("Market sentiment news")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Most positive headlines")
            for h in sentiment["top_positive"]:
                st.write(f"**{h.symbol}** ({h.sentiment_score:+.2f}) - {h.title}")
                st.caption(h.link)

        with col2:
            st.markdown("#### Most negative headlines")
            for h in sentiment["top_negative"]:
                st.write(f"**{h.symbol}** ({h.sentiment_score:+.2f}) - {h.title}")
                st.caption(h.link)

    with tab4:
        st.subheader("Automation status")
        st.markdown(
            "- Use **GitHub Actions** (`.github/workflows/daily-scan.yml`) for free weekday automation.\n"
            "- Use backend run mode for email alerts at 7 AM.\n"
            "- For mobile app, wrap this experience with React Native/Flutter and call your API endpoints."
        )
        st.code("RUN_MODE=once SEND_EMAIL=false python app/main.py", language="bash")
        st.code("streamlit run app/frontend_app.py", language="bash")

else:
    st.info("Configure settings in the sidebar and click **Run Scan**.")
    st.markdown(
        "This app supports day-trading and long-term workflows and includes sentiment news analysis."
    )
