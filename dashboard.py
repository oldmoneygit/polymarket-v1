"""Streamlit dashboard for the Polymarket Copy Trading Bot."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("data/polymarket_bot.db")

# ── Page config ──────────────────────────────────────────────

st.set_page_config(
    page_title="Polymarket Bot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_resource
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_connection()
    return pd.read_sql_query(sql, conn, params=params)


def scalar(sql: str, params: tuple = ()) -> object:
    conn = get_connection()
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


# ── Sidebar ──────────────────────────────────────────────────

with st.sidebar:
    st.title("Polymarket Bot")
    auto_refresh = st.toggle("Auto-refresh (10s)", value=True)
    if auto_refresh:
        st.caption("Dashboard atualiza automaticamente")

# ── Header metrics ───────────────────────────────────────────

st.title("📊 Polymarket Copy Trading Bot")

now = datetime.now(timezone.utc)
today_start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())
today_end = today_start + 86400

open_count = scalar("SELECT count(*) FROM positions WHERE status = 'open'")
total_exposure = scalar(
    "SELECT COALESCE(SUM(usdc_invested), 0) FROM positions WHERE status = 'open'"
)
daily_pnl = scalar(
    "SELECT COALESCE(SUM(pnl), 0) FROM positions "
    "WHERE closed_at >= ? AND closed_at < ? AND pnl IS NOT NULL",
    (today_start, today_end),
)
total_pnl = scalar(
    "SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE pnl IS NOT NULL"
)
total_trades = scalar("SELECT count(*) FROM positions")
seen_hashes = scalar("SELECT count(*) FROM seen_hashes")
paused = scalar("SELECT value FROM bot_state WHERE key = 'paused'") or "false"

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Status", "PAUSADO" if paused == "true" else "ATIVO")
col2.metric("Posicoes Abertas", f"{open_count}")
col3.metric("Exposicao", f"${float(total_exposure):.2f}")
col4.metric("P&L Hoje", f"${float(daily_pnl):+.2f}")
col5.metric("P&L Total", f"${float(total_pnl):+.2f}")
col6.metric("Trades Detectados", f"{seen_hashes}")

st.divider()

# ── Open positions ───────────────────────────────────────────

st.subheader("Posicoes Abertas")

open_df = query("""
    SELECT
        id,
        market_title AS mercado,
        outcome AS lado,
        entry_price AS preco,
        shares,
        usdc_invested AS investido,
        trader_copied AS trader,
        datetime(opened_at, 'unixepoch') AS aberto_em,
        CASE WHEN dry_run = 1 THEN 'DRY RUN' ELSE 'LIVE' END AS modo
    FROM positions
    WHERE status = 'open'
    ORDER BY opened_at DESC
""")

if open_df.empty:
    st.info("Nenhuma posicao aberta")
else:
    open_df["trader"] = open_df["trader"].str[:10] + "..."
    st.dataframe(open_df, use_container_width=True, hide_index=True)

st.divider()

# ── Recent activity (all detected trades via seen_hashes) ────

st.subheader("Atividade Recente (Trades Detectados)")

col_left, col_right = st.columns(2)

with col_left:
    recent_hashes = query("""
        SELECT
            hash,
            trader_wallet AS trader,
            datetime(created_at, 'unixepoch') AS detectado_em
        FROM seen_hashes
        ORDER BY created_at DESC
        LIMIT 50
    """)
    if not recent_hashes.empty:
        recent_hashes["trader"] = recent_hashes["trader"].str[:10] + "..."
        recent_hashes["hash"] = recent_hashes["hash"].str[:14] + "..."
        st.dataframe(recent_hashes, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum trade detectado ainda")

with col_right:
    # Trades per trader
    trader_counts = query("""
        SELECT
            trader_wallet AS trader,
            count(*) AS trades
        FROM seen_hashes
        GROUP BY trader_wallet
        ORDER BY trades DESC
    """)
    if not trader_counts.empty:
        trader_counts["trader"] = trader_counts["trader"].str[:10] + "..."
        st.bar_chart(trader_counts.set_index("trader")["trades"])

st.divider()

# ── Closed positions / P&L history ──────────────────────────

st.subheader("Historico de Posicoes Fechadas")

closed_df = query("""
    SELECT
        id,
        market_title AS mercado,
        outcome AS lado,
        entry_price AS preco,
        usdc_invested AS investido,
        pnl,
        status AS resultado,
        datetime(opened_at, 'unixepoch') AS aberto_em,
        datetime(closed_at, 'unixepoch') AS fechado_em,
        CASE WHEN dry_run = 1 THEN 'DRY RUN' ELSE 'LIVE' END AS modo
    FROM positions
    WHERE status != 'open'
    ORDER BY closed_at DESC
    LIMIT 100
""")

if closed_df.empty:
    st.info("Nenhuma posicao fechada ainda — aguardando resolucao dos mercados")
else:
    st.dataframe(closed_df, use_container_width=True, hide_index=True)

# ── Trades by trader (all positions) ────────────────────────

st.divider()
st.subheader("Trades Executados por Trader")

trader_positions = query("""
    SELECT
        trader_copied AS trader,
        count(*) AS total,
        SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS abertas,
        SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS ganhas,
        SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS perdidas,
        ROUND(SUM(usdc_invested), 2) AS total_investido,
        ROUND(COALESCE(SUM(pnl), 0), 2) AS pnl
    FROM positions
    GROUP BY trader_copied
    ORDER BY total DESC
""")

if not trader_positions.empty:
    trader_positions["trader"] = trader_positions["trader"].str[:10] + "..."
    st.dataframe(trader_positions, use_container_width=True, hide_index=True)

# ── Strategy signals (from log file) ─────────────────────────

st.divider()
st.subheader("Sinais de Estrategia (ultimas 24h)")

log_path = Path("logs/bot.log")
if log_path.exists():
    log_text = log_path.read_text(encoding="utf-8", errors="ignore")
    lines = log_text.strip().split("\n")

    col_conf, col_scan, col_mom = st.columns(3)

    with col_conf:
        st.markdown("**Confluencia** (2+ traders)")
        confluence_lines = [l for l in lines[-500:] if "CONFLUENCE" in l]
        if confluence_lines:
            for line in confluence_lines[-10:]:
                st.text(line.split("CONFLUENCE")[1][:80] if "CONFLUENCE" in line else "")
        else:
            st.caption("Nenhuma confluencia detectada ainda")

    with col_scan:
        st.markdown("**Scanner** (high-prob)")
        scanner_lines = [l for l in lines[-500:] if "SCANNER:" in l]
        if scanner_lines:
            for line in scanner_lines[-10:]:
                st.text(line.split("SCANNER:")[1][:80] if "SCANNER:" in line else "")
        else:
            st.caption("Nenhum sinal de scanner ainda")

    with col_mom:
        st.markdown("**Momentum** (price moves)")
        momentum_lines = [l for l in lines[-500:] if "MOMENTUM" in l]
        if momentum_lines:
            for line in momentum_lines[-10:]:
                st.text(line.split("MOMENTUM")[1][:80] if "MOMENTUM" in line else "")
        else:
            st.caption("Nenhum movimento detectado ainda")
else:
    st.info("Log file nao encontrado. Inicie o bot primeiro.")

# ── Auto-refresh ─────────────────────────────────────────────

if auto_refresh:
    time.sleep(10)
    st.rerun()
