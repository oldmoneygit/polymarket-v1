"""Polymarket Copy Trading Bot — Real-time Dashboard."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
import streamlit as st

# Must be first Streamlit call
st.set_page_config(
    page_title="Polymarket Bot Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

import aiohttp

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TRADER_WALLETS: dict[str, dict[str, str]] = {
    "0xf195721ad850377c96cd634457c70cd9e8308057": {"name": "JaJackson", "tier": "S", "focus": "NHL"},
    "0xa8e089ade142c95538e06196e09c85681112ad50": {"name": "Wannac", "tier": "S", "focus": "NBA high-prob"},
    "0x492442eab586f242b53bda933fd5de859c8a3782": {"name": "0x4924 (anon)", "tier": "S", "focus": "NBA totals"},
    "0xead152b855effa6b5b5837f53b24c0756830c76a": {"name": "elkmonkey", "tier": "A", "focus": "Multi-sport"},
    "0x02227b8f5a9636e895607edd3185ed6ee5598ff7": {"name": "HorizonSplendidView", "tier": "A", "focus": "UCL"},
    "0xc2e7800b5af46e6093872b177b7a5e7f0563be51": {"name": "beachboy4", "tier": "A", "focus": "MLS"},
    "0x37c1874a60d348903594a96703e0507c518fc53a": {"name": "CemeterySun", "tier": "A", "focus": "NBA spreads"},
    "0xd106952ebf30a3125affd8a23b6c1f30c35fc79c": {"name": "Herdonia", "tier": "A", "focus": "NBA totals"},
}

DATA_API = "https://data-api.polymarket.com"

SPORTS_KEYWORDS = [
    "soccer", "football", "mls", "ucl", "epl", "laliga",
    "bundesliga", "seriea", "ligue1", "premier", "champions",
    "copa", "world-cup", "nba", "nfl", "mlb", "nhl",
    "cbb-", "ncaa", "ncaab", "college",
    "ufc-", "boxing", "tennis", "golf", "formula1",
    "spread", "total", "o-u", "moneyline",
    "win-on", "beat", "match", "game",
]


def is_sports(slug: str) -> bool:
    s = slug.lower()
    return any(kw in s for kw in SPORTS_KEYWORDS)


# ---------------------------------------------------------------------------
# Data fetching (cached)
# ---------------------------------------------------------------------------

async def _fetch_activity(wallet: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch recent trades from Polymarket Data API."""
    url = f"{DATA_API}/activity"
    params = {"user": wallet, "type": "TRADE", "limit": str(limit)}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            return []


def fetch_activity(wallet: str, limit: int = 50) -> list[dict[str, Any]]:
    """Sync wrapper for async fetch."""
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_fetch_activity(wallet, limit))
        loop.close()
        return result
    except Exception:
        return []


@st.cache_data(ttl=30)
def fetch_all_traders(limit_per_trader: int = 30) -> pd.DataFrame:
    """Fetch recent trades from all monitored traders."""
    rows: list[dict[str, Any]] = []
    for wallet, info in TRADER_WALLETS.items():
        trades = fetch_activity(wallet, limit_per_trader)
        for t in trades:
            ts = t.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
            usdc = t.get("usdcSize", 0)
            price = t.get("price", 0)
            slug = t.get("slug", "") or t.get("eventSlug", "")
            rows.append({
                "Trader": info["name"],
                "Tier": info["tier"],
                "Focus": info["focus"],
                "Time (UTC)": dt,
                "Side": t.get("side", ""),
                "Outcome": t.get("outcome", ""),
                "Market": t.get("title", "")[:60],
                "Slug": slug,
                "Price": round(price, 4) if price else 0,
                "USDC": round(usdc, 2) if usdc else 0,
                "Shares": round(t.get("size", 0), 2),
                "Sport": is_sports(slug),
                "Wallet": wallet[:10] + "...",
                "Hash": (t.get("transactionHash", "") or "")[:12] + "...",
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "Time (UTC)" in df.columns and not df.empty:
        df = df.sort_values("Time (UTC)", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def main() -> None:
    # Header
    st.markdown(
        """
        <h1 style='text-align:center; margin-bottom:0;'>
            🔍 Polymarket Copy Trading Dashboard
        </h1>
        <p style='text-align:center; color:#888; margin-top:0;'>
            Real-time trader monitoring &bull; 8 wallets &bull; Sports markets
        </p>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar
    with st.sidebar:
        st.header("Controls")
        auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)
        if st.button("Refresh Now"):
            st.cache_data.clear()

        st.divider()
        st.header("Filters")
        tier_filter = st.multiselect("Tier", ["S", "A"], default=["S", "A"])
        sports_only = st.checkbox("Sports only", value=False)
        min_usdc = st.slider("Min USDC per trade", 0, 10000, 0, step=50)

        st.divider()
        st.header("Traders Monitored")
        for wallet, info in TRADER_WALLETS.items():
            tier_badge = "🏆" if info["tier"] == "S" else "✅"
            st.markdown(f"{tier_badge} **{info['name']}** — {info['focus']}")

    # Fetch data
    with st.spinner("Fetching live data from Polymarket..."):
        df = fetch_all_traders(30)

    if df.empty:
        st.warning("No data received. API might be down or rate-limited.")
        return

    # Apply filters
    mask = df["Tier"].isin(tier_filter)
    if sports_only:
        mask &= df["Sport"] == True
    if min_usdc > 0:
        mask &= df["USDC"] >= min_usdc
    df_filtered = df[mask].copy()

    # ---------------------------------------------------------------------------
    # KPI row
    # ---------------------------------------------------------------------------
    now_utc = datetime.now(timezone.utc)
    last_hour = now_utc - timedelta(hours=1)

    recent_mask = pd.Series([False] * len(df_filtered), index=df_filtered.index)
    if "Time (UTC)" in df_filtered.columns and not df_filtered.empty:
        recent_mask = df_filtered["Time (UTC)"].apply(
            lambda x: x is not None and x >= last_hour if pd.notna(x) else False
        )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Trades", len(df_filtered))
    with col2:
        st.metric("Last Hour", int(recent_mask.sum()))
    with col3:
        total_usdc = df_filtered["USDC"].sum()
        st.metric("Total USDC", f"${total_usdc:,.0f}")
    with col4:
        unique_markets = df_filtered["Market"].nunique()
        st.metric("Unique Markets", unique_markets)
    with col5:
        active_traders = df_filtered["Trader"].nunique()
        st.metric("Active Traders", f"{active_traders}/8")

    st.divider()

    # ---------------------------------------------------------------------------
    # Live Feed
    # ---------------------------------------------------------------------------
    st.subheader("📡 Live Trade Feed")

    if not df_filtered.empty:
        # Color-code by tier
        def highlight_tier(row: pd.Series) -> list[str]:
            if row.get("Tier") == "S":
                return ["background-color: rgba(255, 215, 0, 0.15)"] * len(row)
            return [""] * len(row)

        display_cols = ["Trader", "Tier", "Time (UTC)", "Side", "Outcome", "Market", "Price", "USDC", "Sport"]
        display_df = df_filtered[display_cols].head(50)

        st.dataframe(
            display_df.style.apply(highlight_tier, axis=1).format({
                "Price": "{:.2%}",
                "USDC": "${:,.2f}",
            }),
            use_container_width=True,
            height=500,
        )
    else:
        st.info("No trades match your filters.")

    # ---------------------------------------------------------------------------
    # Charts
    # ---------------------------------------------------------------------------
    st.divider()
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("💰 Volume by Trader")
        if not df_filtered.empty:
            vol_by_trader = df_filtered.groupby("Trader")["USDC"].sum().sort_values(ascending=True)
            st.bar_chart(vol_by_trader)

    with chart_col2:
        st.subheader("🎯 Trades by Market")
        if not df_filtered.empty:
            trades_by_market = df_filtered["Market"].value_counts().head(10)
            st.bar_chart(trades_by_market)

    # ---------------------------------------------------------------------------
    # Tier S Highlights
    # ---------------------------------------------------------------------------
    st.divider()
    st.subheader("🏆 Tier S — High Conviction Signals")

    tier_s = df_filtered[df_filtered["Tier"] == "S"].copy()
    if not tier_s.empty:
        # Group by market to find position building
        grouped = tier_s.groupby(["Trader", "Market"]).agg(
            trades=("USDC", "count"),
            total_usdc=("USDC", "sum"),
            avg_price=("Price", "mean"),
            last_time=("Time (UTC)", "max"),
        ).reset_index().sort_values("total_usdc", ascending=False)

        for _, row in grouped.head(10).iterrows():
            trades_count = int(row["trades"])
            conviction = "🔥🔥🔥" if trades_count >= 5 else ("🔥🔥" if trades_count >= 3 else "🔥")
            st.markdown(
                f"**{row['Trader']}** {conviction} "
                f"| {row['Market']} "
                f"| {trades_count} trades "
                f"| **${row['total_usdc']:,.0f}** invested "
                f"| avg price {row['avg_price']:.0%}"
            )
    else:
        st.info("No Tier S activity in current view.")

    # ---------------------------------------------------------------------------
    # Raw data expander
    # ---------------------------------------------------------------------------
    with st.expander("📋 Raw Data (all columns)"):
        st.dataframe(df_filtered, use_container_width=True)

    # ---------------------------------------------------------------------------
    # Footer
    # ---------------------------------------------------------------------------
    st.divider()
    st.caption(
        f"Last updated: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC | "
        f"Data: Polymarket Data API | "
        f"Auto-refresh: {'ON' if auto_refresh else 'OFF'}"
    )

    # Auto-refresh
    if auto_refresh:
        time.sleep(30)
        st.rerun()


if __name__ == "__main__":
    main()
