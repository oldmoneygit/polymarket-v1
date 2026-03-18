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
    "0x9eb9133542965213982f3db49097f6cc4184cb5d": {"name": "Stealcopper2gamble", "tier": "S", "focus": "Valorant esports"},
    "0x6ffb4354cbe6e0f9989e3b55564ec5fb8646a834": {"name": "AgricultureSecretary", "tier": "A", "focus": "Politics/Geopolitics"},
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
            "Strategy": r["strategy"] if "strategy" in r.keys() else "copy_sports",
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

    # ── Strategy breakdown ───────────────────────────────────────
    STRATEGY_LABELS = {
        "copy_sports": "Esportes/Esports",
        "copy_geopolitical": "Geopolitica/Certezas",
        "ultra_fast": "Ultra-Rapido (5min/15min)",
    }
    STRATEGY_COLORS = {
        "copy_sports": "#3b82f6",
        "copy_geopolitical": "#f59e0b",
        "ultra_fast": "#ef4444",
    }

    if not positions_df.empty and "Strategy" in positions_df.columns:
        st.divider()
        scols = st.columns(3)
        for i, (strat_key, strat_label) in enumerate(STRATEGY_LABELS.items()):
            with scols[i]:
                strat_df = positions_df[positions_df["Strategy"] == strat_key]
                strat_open = strat_df[strat_df["Status"] == "open"]
                strat_closed = strat_df[strat_df["Status"] != "open"]
                strat_pnl = strat_closed["PnL"].sum() if not strat_closed.empty else 0.0
                strat_exp = strat_open["Invested"].sum() if not strat_open.empty else 0.0
                color = STRATEGY_COLORS[strat_key]
                pnl_c = "#22c55e" if strat_pnl >= 0 else "#ef4444"
                st.markdown(
                    f"<div style='border-left:4px solid {color}; padding:8px 12px;'>"
                    f"<b style='color:{color}'>{strat_label}</b><br/>"
                    f"<span style='color:{pnl_c};font-size:1.3rem;font-weight:700'>P&L: ${strat_pnl:+.2f}</span><br/>"
                    f"<span style='color:#888'>{len(strat_open)} pos | ${strat_exp:.2f} exp</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ── Tabs ──────────────────────────────────────────────────────
    tab_s1, tab_s2, tab_s3, tab_pnl, tab_feed = st.tabs([
        "Esportes", "Geopolitica", "Ultra-Rapido", "P&L Global", "Trade Feed"
    ])

    # ── Helper: render strategy tab ─────────────────────────────
    def render_strategy_tab(strat_key: str, strat_label: str) -> None:
        if positions_df.empty or "Strategy" not in positions_df.columns:
            st.info(f"Sem dados para {strat_label}.")
            return

        strat_df = positions_df[positions_df["Strategy"] == strat_key]
        if strat_df.empty:
            st.info(f"Nenhuma posicao em {strat_label} ainda.")
            return

        s_open = strat_df[strat_df["Status"] == "open"]
        s_closed = strat_df[strat_df["Status"] != "open"]
        s_pnl = s_closed["PnL"].sum() if not s_closed.empty else 0.0
        s_wins = len(s_closed[s_closed["Status"] == "won"]) if not s_closed.empty else 0
        s_losses = len(s_closed[s_closed["Status"] == "lost"]) if not s_closed.empty else 0
        s_tp = len(s_closed[s_closed["Status"] == "sold"]) if not s_closed.empty else 0

        # KPIs
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("P&L", f"${s_pnl:+.2f}")
        with c2:
            st.metric("Abertas", len(s_open))
        with c3:
            st.metric("Take-Profit", s_tp)
        with c4:
            wr = s_wins / (s_wins + s_losses) if (s_wins + s_losses) > 0 else 0
            st.metric("Win Rate", f"{wr:.0%}" if (s_wins + s_losses) > 0 else "N/A")

        # Open positions
        if not s_open.empty:
            st.subheader("Posicoes Abertas")
            cols = ["Market", "Outcome", "Entry", "Invested", "Trader", "Opened"]
            disp = s_open[[c for c in cols if c in s_open.columns]].copy()
            if "Entry" in disp.columns:
                disp["Entry"] = disp["Entry"].apply(lambda x: f"{x:.0%}")
            if "Invested" in disp.columns:
                disp["Invested"] = disp["Invested"].apply(lambda x: f"${x:.2f}")
            if "Opened" in disp.columns:
                disp["Opened"] = disp["Opened"].apply(lambda x: x.strftime("%m/%d %H:%M") if x else "")
            st.dataframe(disp, use_container_width=True, height=min(300, 40 + len(disp) * 35))

        # Closed positions
        if not s_closed.empty:
            st.subheader("Historico")
            cols2 = ["Market", "Outcome", "PnL", "Status", "Trader", "Closed"]
            disp2 = s_closed[[c for c in cols2 if c in s_closed.columns]].copy()
            if "PnL" in disp2.columns:
                disp2["PnL"] = disp2["PnL"].apply(lambda x: f"${x:+.2f}")
            if "Status" in disp2.columns:
                disp2["Status"] = disp2["Status"].str.upper()
            if "Closed" in disp2.columns:
                disp2["Closed"] = disp2["Closed"].apply(lambda x: x.strftime("%m/%d %H:%M") if x else "")
            st.dataframe(disp2, use_container_width=True, height=min(300, 40 + len(disp2) * 35))

    # ── Strategy Tabs ─────────────────────────────────────────────
    with tab_s1:
        render_strategy_tab("copy_sports", "Copy Trading Esportes")

    with tab_s2:
        render_strategy_tab("copy_geopolitical", "Copy Trading Geopolitica")

    with tab_s3:
        render_strategy_tab("ultra_fast", "Ultra-Rapido (5min/15min)")

    # ── Global P&L Tab ────────────────────────────────────────────
    with tab_pnl:
        if closed_pos.empty:
            st.info("Nenhuma posicao resolvida ainda.")
        else:
            if not daily_pnl_df.empty:
                st.line_chart(daily_pnl_df.set_index("Date")["Cumulative"], color="#22c55e")
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

    # ── Trade Feed Tab ────────────────────────────────────────────
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
            f"Max exposicao: $200\n"
            f"Estrategias: 3\n"
            f"Traders: 17 wallets\n"
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
