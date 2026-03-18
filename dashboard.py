"""Polymarket Copy Trading Bot — Real-time Dashboard with P&L tracking."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Polymarket Bot",
    page_icon="\U0001f4b0",
    layout="wide",
    initial_sidebar_state="expanded",
)

import aiohttp

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = Path("data/polymarket_bot.db")

TRADER_WALLETS: dict[str, dict[str, str]] = {
    "0xf195721ad850377c96cd634457c70cd9e8308057": {"name": "JaJackson", "tier": "S", "focus": "NHL"},
    "0xa8e089ade142c95538e06196e09c85681112ad50": {"name": "Wannac", "tier": "S", "focus": "NBA high-prob"},
    "0x492442eab586f242b53bda933fd5de859c8a3782": {"name": "0x4924", "tier": "S", "focus": "NBA totals"},
    "0xead152b855effa6b5b5837f53b24c0756830c76a": {"name": "elkmonkey", "tier": "A", "focus": "Multi-sport"},
    "0x02227b8f5a9636e895607edd3185ed6ee5598ff7": {"name": "HorizonSplendidView", "tier": "A", "focus": "UCL"},
    "0xc2e7800b5af46e6093872b177b7a5e7f0563be51": {"name": "beachboy4", "tier": "A", "focus": "MLS"},
    "0x37c1874a60d348903594a96703e0507c518fc53a": {"name": "CemeterySun", "tier": "A", "focus": "NBA spreads"},
    "0xd106952ebf30a3125affd8a23b6c1f30c35fc79c": {"name": "Herdonia", "tier": "A", "focus": "NBA totals"},
}

DATA_API = "https://data-api.polymarket.com"

TRADER_NAME_MAP = {v["name"]: k for k, v in TRADER_WALLETS.items()}


def _trader_name(wallet: str) -> str:
    wallet_lower = wallet.lower()
    for addr, info in TRADER_WALLETS.items():
        if wallet_lower.startswith(addr[:10]):
            return info["name"]
    return wallet[:10] + "..."


# ---------------------------------------------------------------------------
# Database reads
# ---------------------------------------------------------------------------

def load_positions() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM positions ORDER BY opened_at DESC").fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    data = []
    for r in rows:
        opened = datetime.fromtimestamp(r["opened_at"], tz=timezone.utc) if r["opened_at"] else None
        closed = datetime.fromtimestamp(r["closed_at"], tz=timezone.utc) if r["closed_at"] else None
        data.append({
            "id": r["id"],
            "Market": r["market_title"][:50],
            "Outcome": r["outcome"],
            "Entry": r["entry_price"],
            "Shares": r["shares"],
            "Invested": r["usdc_invested"],
            "Status": r["status"],
            "PnL": r["pnl"] if r["pnl"] is not None else 0.0,
            "Trader": _trader_name(r["trader_copied"]),
            "Opened": opened,
            "Closed": closed,
            "Dry Run": bool(r["dry_run"]),
        })
    return pd.DataFrame(data)


def load_daily_pnl(days: int = 30) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = int(time.time()) - (days * 86400)
    rows = conn.execute(
        "SELECT closed_at, pnl FROM positions WHERE closed_at >= ? AND pnl IS NOT NULL ORDER BY closed_at",
        (cutoff,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    daily: dict[str, float] = {}
    for closed_at, pnl in rows:
        d = datetime.fromtimestamp(closed_at, tz=timezone.utc).strftime("%Y-%m-%d")
        daily[d] = daily.get(d, 0.0) + pnl
    df = pd.DataFrame(list(daily.items()), columns=["Date", "PnL"])
    df["Cumulative"] = df["PnL"].cumsum()
    return df


def load_bot_state() -> dict[str, str]:
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT key, value FROM bot_state").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# API data fetching
# ---------------------------------------------------------------------------

async def _fetch_activity(wallet: str, limit: int = 50) -> list[dict[str, Any]]:
    url = f"{DATA_API}/activity"
    params = {"user": wallet, "type": "TRADE", "limit": str(limit)}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            return []


def fetch_activity(wallet: str, limit: int = 50) -> list[dict[str, Any]]:
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_fetch_activity(wallet, limit))
        loop.close()
        return result
    except Exception:
        return []


@st.cache_data(ttl=30)
def fetch_all_traders(limit_per_trader: int = 30) -> pd.DataFrame:
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
                "Time": dt,
                "Side": t.get("side", ""),
                "Outcome": t.get("outcome", ""),
                "Market": t.get("title", "")[:55],
                "Price": round(price, 4) if price else 0,
                "USDC": round(usdc, 2) if usdc else 0,
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "Time" in df.columns and not df.empty:
        df = df.sort_values("Time", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------------

def color_pnl(val: float) -> str:
    if val > 0:
        return "color: #22c55e; font-weight: bold"
    if val < 0:
        return "color: #ef4444; font-weight: bold"
    return "color: #888"


def color_status(val: str) -> str:
    colors = {"open": "#3b82f6", "won": "#22c55e", "lost": "#ef4444", "sold": "#f59e0b"}
    c = colors.get(val, "#888")
    return f"color: {c}; font-weight: bold"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def main() -> None:
    now_utc = datetime.now(timezone.utc)

    # Load bot data
    positions_df = load_positions()
    daily_pnl_df = load_daily_pnl()
    bot_state = load_bot_state()

    open_pos = positions_df[positions_df["Status"] == "open"] if not positions_df.empty else pd.DataFrame()
    closed_pos = positions_df[positions_df["Status"] != "open"] if not positions_df.empty else pd.DataFrame()

    total_pnl = closed_pos["PnL"].sum() if not closed_pos.empty else 0.0
    total_invested = open_pos["Invested"].sum() if not open_pos.empty else 0.0
    today_str = now_utc.strftime("%Y-%m-%d")
    today_pnl = 0.0
    if not daily_pnl_df.empty and today_str in daily_pnl_df["Date"].values:
        today_pnl = daily_pnl_df[daily_pnl_df["Date"] == today_str]["PnL"].iloc[0]

    wins = len(closed_pos[closed_pos["Status"] == "won"]) if not closed_pos.empty else 0
    losses = len(closed_pos[closed_pos["Status"] == "lost"]) if not closed_pos.empty else 0
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

    is_paused = bot_state.get("paused", "false") == "true"
    is_dry_run = True  # Read from positions
    if not positions_df.empty and "Dry Run" in positions_df.columns:
        is_dry_run = positions_df["Dry Run"].any()

    # ── Header ────────────────────────────────────────────────────
    mode_badge = "DRY RUN" if is_dry_run else "LIVE"
    status_badge = "PAUSADO" if is_paused else "ATIVO"
    status_color = "#ef4444" if is_paused else "#22c55e"

    st.markdown(
        f"""
        <div style='text-align:center; margin-bottom:1rem;'>
            <h1 style='margin-bottom:0.2rem;'>Polymarket Copy Trading Bot</h1>
            <span style='background:{status_color}; color:white; padding:4px 12px; border-radius:12px; font-size:0.85rem; font-weight:600;'>{status_badge}</span>
            <span style='background:#3b82f6; color:white; padding:4px 12px; border-radius:12px; font-size:0.85rem; font-weight:600; margin-left:8px;'>{mode_badge}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── P&L KPIs ──────────────────────────────────────────────────
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"
        st.markdown(f"<div style='text-align:center'><p style='margin:0;color:#888;font-size:0.8rem'>P&L Total</p><p style='margin:0;color:{pnl_color};font-size:1.8rem;font-weight:700'>${total_pnl:+.2f}</p></div>", unsafe_allow_html=True)
    with k2:
        today_color = "#22c55e" if today_pnl >= 0 else "#ef4444"
        st.markdown(f"<div style='text-align:center'><p style='margin:0;color:#888;font-size:0.8rem'>P&L Hoje</p><p style='margin:0;color:{today_color};font-size:1.8rem;font-weight:700'>${today_pnl:+.2f}</p></div>", unsafe_allow_html=True)
    with k3:
        st.markdown(f"<div style='text-align:center'><p style='margin:0;color:#888;font-size:0.8rem'>Win Rate</p><p style='margin:0;color:white;font-size:1.8rem;font-weight:700'>{win_rate:.0%}</p></div>", unsafe_allow_html=True)
    with k4:
        st.markdown(f"<div style='text-align:center'><p style='margin:0;color:#888;font-size:0.8rem'>Posicoes Abertas</p><p style='margin:0;color:#3b82f6;font-size:1.8rem;font-weight:700'>{len(open_pos)}</p></div>", unsafe_allow_html=True)
    with k5:
        st.markdown(f"<div style='text-align:center'><p style='margin:0;color:#888;font-size:0.8rem'>Exposicao</p><p style='margin:0;color:white;font-size:1.8rem;font-weight:700'>${total_invested:.2f}</p></div>", unsafe_allow_html=True)
    with k6:
        st.markdown(f"<div style='text-align:center'><p style='margin:0;color:#888;font-size:0.8rem'>W / L</p><p style='margin:0;color:white;font-size:1.8rem;font-weight:700'>{wins} / {losses}</p></div>", unsafe_allow_html=True)

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────
    tab_positions, tab_pnl, tab_feed, tab_traders = st.tabs([
        "Posicoes Abertas", "P&L", "Trade Feed", "Traders"
    ])

    # ── TAB 1: Posicoes Abertas ───────────────────────────────────
    with tab_positions:
        if open_pos.empty:
            st.info("Nenhuma posicao aberta no momento.")
        else:
            st.subheader(f"Posicoes Abertas ({len(open_pos)})")

            display = open_pos[["Market", "Outcome", "Entry", "Shares", "Invested", "Trader", "Opened"]].copy()
            display["Entry"] = display["Entry"].apply(lambda x: f"{x:.0%}")
            display["Invested"] = display["Invested"].apply(lambda x: f"${x:.2f}")
            display["Shares"] = display["Shares"].apply(lambda x: f"{x:.2f}")
            if "Opened" in display.columns:
                display["Opened"] = display["Opened"].apply(
                    lambda x: x.strftime("%m/%d %H:%M") if x else ""
                )

            st.dataframe(display, use_container_width=True, height=min(400, 40 + len(display) * 35))

            # Group by trader
            st.subheader("Exposicao por Trader")
            by_trader = open_pos.groupby("Trader").agg(
                positions=("Invested", "count"),
                total=("Invested", "sum"),
            ).sort_values("total", ascending=False)
            st.bar_chart(by_trader["total"])

    # ── TAB 2: P&L ────────────────────────────────────────────────
    with tab_pnl:
        if closed_pos.empty:
            st.info("Nenhuma posicao resolvida ainda. Aguardando mercados resolverem...")
        else:
            st.subheader("Historico de P&L")

            # P&L curve
            if not daily_pnl_df.empty:
                st.line_chart(daily_pnl_df.set_index("Date")["Cumulative"], color="#22c55e")

            # Closed positions table
            st.subheader(f"Posicoes Fechadas ({len(closed_pos)})")
            closed_display = closed_pos[["Market", "Outcome", "Entry", "Invested", "PnL", "Status", "Trader", "Closed"]].copy()
            closed_display["Entry"] = closed_display["Entry"].apply(lambda x: f"{x:.0%}")
            closed_display["Invested"] = closed_display["Invested"].apply(lambda x: f"${x:.2f}")
            closed_display["PnL"] = closed_display["PnL"].apply(lambda x: f"${x:+.2f}")
            closed_display["Status"] = closed_display["Status"].str.upper()
            if "Closed" in closed_display.columns:
                closed_display["Closed"] = closed_display["Closed"].apply(
                    lambda x: x.strftime("%m/%d %H:%M") if x else ""
                )

            st.dataframe(closed_display, use_container_width=True, height=min(400, 40 + len(closed_display) * 35))

            # Stats
            col1, col2, col3 = st.columns(3)
            with col1:
                avg_win = closed_pos[closed_pos["PnL"] > 0]["PnL"].mean() if wins > 0 else 0
                st.metric("Avg Win", f"${avg_win:+.2f}")
            with col2:
                avg_loss = closed_pos[closed_pos["PnL"] < 0]["PnL"].mean() if losses > 0 else 0
                st.metric("Avg Loss", f"${avg_loss:.2f}")
            with col3:
                profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
                st.metric("Profit Factor", f"{profit_factor:.2f}")

    # ── TAB 3: Live Trade Feed ────────────────────────────────────
    with tab_feed:
        with st.spinner("Buscando trades dos traders..."):
            df = fetch_all_traders(30)

        if df.empty:
            st.warning("Sem dados da API.")
        else:
            st.subheader("Ultimos Trades dos Traders Monitorados")

            def highlight_tier(row: pd.Series) -> list[str]:
                if row.get("Tier") == "S":
                    return ["background-color: rgba(255, 215, 0, 0.1)"] * len(row)
                return [""] * len(row)

            display_cols = ["Trader", "Tier", "Time", "Side", "Outcome", "Market", "Price", "USDC"]
            st.dataframe(
                df[display_cols].head(50).style.apply(highlight_tier, axis=1).format({
                    "Price": "{:.0%}",
                    "USDC": "${:,.0f}",
                }),
                use_container_width=True,
                height=500,
            )

    # ── TAB 4: Traders ────────────────────────────────────────────
    with tab_traders:
        st.subheader("Traders Monitorados")

        for wallet, info in TRADER_WALLETS.items():
            tier_badge = "S" if info["tier"] == "S" else "A"
            tier_color = "#eab308" if info["tier"] == "S" else "#3b82f6"

            # Count positions from this trader
            trader_positions = 0
            trader_invested = 0.0
            if not open_pos.empty:
                tp = open_pos[open_pos["Trader"] == info["name"]]
                trader_positions = len(tp)
                trader_invested = tp["Invested"].sum()

            st.markdown(
                f"""
                <div style='display:flex; align-items:center; gap:12px; padding:8px 0; border-bottom:1px solid #333;'>
                    <span style='background:{tier_color}; color:white; padding:2px 8px; border-radius:8px; font-size:0.75rem; font-weight:700;'>{tier_badge}</span>
                    <div>
                        <strong>{info['name']}</strong> <span style='color:#888'>— {info['focus']}</span><br/>
                        <code style='font-size:0.7rem'>{wallet}</code>
                    </div>
                    <div style='margin-left:auto; text-align:right;'>
                        <span style='color:#3b82f6'>{trader_positions} pos</span> |
                        <span>${trader_invested:.2f}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ── Sidebar ───────────────────────────────────────────────────
    with st.sidebar:
        st.header("Controles")
        auto_refresh = st.checkbox("Auto-refresh (15s)", value=True)
        if st.button("Atualizar Agora"):
            st.cache_data.clear()

        st.divider()
        st.header("Config Ativa")
        st.code(
            f"Capital/trade: $2.00\n"
            f"Max exposicao: $100\n"
            f"Max prob: 75%\n"
            f"Max age: 30min\n"
            f"Take profit: 15%\n"
            f"Copy SELL: ON\n"
            f"Confluencia: ON",
            language=None,
        )

        st.divider()
        st.caption(
            f"Atualizado: {now_utc.strftime('%H:%M:%S')} UTC\n"
            f"DB: {'OK' if DB_PATH.exists() else 'N/A'}"
        )

    # Auto-refresh
    if auto_refresh:
        time.sleep(15)
        st.rerun()


if __name__ == "__main__":
    main()
