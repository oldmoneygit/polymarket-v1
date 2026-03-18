"""Daily AI Analysis Pipeline — exports trading data and generates analysis prompt.

Usage:
    python daily_report.py                # Export data + generate prompt
    python daily_report.py --analyze      # Export + send to OpenClaw for analysis
    python daily_report.py --telegram     # Export + analyze + send to Telegram
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any

import aiohttp

from src.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = Path("data/polymarket_bot.db")
REPORTS_DIR = Path("reports")
DATA_API = "https://data-api.polymarket.com"

TRADER_INFO: dict[str, dict[str, str]] = {
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


def _trader_name(wallet: str) -> str:
    wallet_lower = wallet.lower()
    for addr, info in TRADER_INFO.items():
        if wallet_lower.startswith(addr[:12]):
            return info["name"]
    return wallet[:10] + "..."


def _trader_tier(wallet: str) -> str:
    wallet_lower = wallet.lower()
    for addr, info in TRADER_INFO.items():
        if wallet_lower.startswith(addr[:12]):
            return info["tier"]
    return "?"


# ---------------------------------------------------------------------------
# Data collection from SQLite
# ---------------------------------------------------------------------------

def collect_bot_data(days: int = 1) -> dict[str, Any]:
    """Collect all trading data from the bot's database."""
    if not DB_PATH.exists():
        return {"error": "Database not found"}

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    now = int(time.time())
    cutoff = now - (days * 86400)

    # All positions
    all_positions = conn.execute(
        "SELECT * FROM positions ORDER BY opened_at DESC"
    ).fetchall()

    # Recent positions (last N days)
    recent = conn.execute(
        "SELECT * FROM positions WHERE opened_at >= ? ORDER BY opened_at DESC",
        (cutoff,),
    ).fetchall()

    # Resolved positions
    resolved = conn.execute(
        "SELECT * FROM positions WHERE status != 'open' AND closed_at >= ? ORDER BY closed_at DESC",
        (cutoff,),
    ).fetchall()

    # Open positions
    open_pos = conn.execute(
        "SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at DESC"
    ).fetchall()

    conn.close()

    # Aggregate stats
    total_pnl = sum(r["pnl"] for r in resolved if r["pnl"] is not None)
    total_invested = sum(r["usdc_invested"] for r in open_pos)
    wins = sum(1 for r in resolved if r["status"] == "won")
    losses = sum(1 for r in resolved if r["status"] == "lost")
    sold = sum(1 for r in resolved if r["status"] == "sold")

    # Per-trader stats
    trader_stats: dict[str, dict[str, Any]] = {}
    for pos in all_positions:
        wallet = pos["trader_copied"]
        name = _trader_name(wallet)
        if name not in trader_stats:
            trader_stats[name] = {
                "tier": _trader_tier(wallet),
                "total_trades": 0,
                "open": 0,
                "won": 0,
                "lost": 0,
                "sold": 0,
                "pnl": 0.0,
                "invested": 0.0,
                "markets": set(),
            }
        s = trader_stats[name]
        s["total_trades"] += 1
        s["markets"].add(pos["market_title"][:40])
        if pos["status"] == "open":
            s["open"] += 1
            s["invested"] += pos["usdc_invested"]
        elif pos["status"] == "won":
            s["won"] += 1
            s["pnl"] += pos["pnl"] or 0
        elif pos["status"] == "lost":
            s["lost"] += 1
            s["pnl"] += pos["pnl"] or 0
        elif pos["status"] == "sold":
            s["sold"] += 1
            s["pnl"] += pos["pnl"] or 0

    # Convert sets to counts
    for s in trader_stats.values():
        s["unique_markets"] = len(s["markets"])
        del s["markets"]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "summary": {
            "total_positions": len(all_positions),
            "open_positions": len(open_pos),
            "resolved": len(resolved),
            "wins": wins,
            "losses": losses,
            "sold_take_profit": sold,
            "win_rate": wins / (wins + losses) if (wins + losses) > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "current_exposure": round(total_invested, 2),
        },
        "trader_performance": trader_stats,
        "open_positions": [
            {
                "market": r["market_title"][:50],
                "outcome": r["outcome"],
                "entry_price": r["entry_price"],
                "invested": r["usdc_invested"],
                "trader": _trader_name(r["trader_copied"]),
                "hours_open": round((now - r["opened_at"]) / 3600, 1),
            }
            for r in open_pos
        ],
        "resolved_positions": [
            {
                "market": r["market_title"][:50],
                "outcome": r["outcome"],
                "status": r["status"],
                "pnl": r["pnl"],
                "invested": r["usdc_invested"],
                "trader": _trader_name(r["trader_copied"]),
            }
            for r in resolved[:20]  # Last 20
        ],
    }


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT = """# Polymarket Copy Trading Bot — Daily Analysis Report

## Your Role
You are a quantitative analyst reviewing a Polymarket prediction market copy trading bot's daily performance. Your job is to evaluate each trader being copied and recommend adjustments.

## Current Bot Configuration
- Capital per trade: $2.00 (fast markets), reduced for slower markets
- Max exposure: $100
- Max probability: 75% (avoid overpaying for "sure things")
- Take profit: 15%
- Markets: ALL categories (sports, crypto, politics, esports)
- Speed allocation: Fast (<6h) = full size, Medium (6-48h) = reduced, Slow (>48h) = skip
- Confluence: 2+ traders agree = boosted size

## Today's Data

{data_json}

## What I Need You To Analyze

### 1. TRADER SCORECARD
For each trader, rate 1-10 and recommend: KEEP, PAUSE, or REMOVE
Consider:
- Win rate (>60% = good, >70% = excellent)
- P&L (positive = good)
- Trade frequency (too many = noise, too few = useless)
- Diversity of markets (specialized = good, random = bad)
- Risk/reward ratio

### 2. PORTFOLIO HEALTH
- Is our exposure well-distributed or concentrated?
- Are we over-exposed to any single sport/market?
- Is the take-profit triggering too early or too late?

### 3. PATTERN DETECTION
- Any traders who are consistently losing? → Remove
- Any traders who win on specific market types? → Note the pattern
- Any confluence signals that led to wins? → Strengthen
- Markets that resolved — did we pick the right side?

### 4. RECOMMENDATIONS
Specific, actionable changes:
- Which traders to add/remove/pause
- Config adjustments (capital, probability range, etc.)
- New market categories to explore or avoid
- Any wallets from the leaderboard worth investigating

### 5. RISK ALERTS
- Any concerning patterns?
- Drawdown warning?
- Over-exposure to a single event?

## Output Format
Respond in Portuguese (BR). Be direct and specific. Use tables where helpful.
Start with a 1-paragraph executive summary, then the detailed analysis.
End with a prioritized TODO list (max 5 items).
"""


def generate_report(data: dict[str, Any], days: int = 1) -> str:
    """Generate the analysis prompt with embedded data."""
    data_json = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    return ANALYSIS_PROMPT.format(data_json=data_json)


# ---------------------------------------------------------------------------
# Report execution
# ---------------------------------------------------------------------------

def save_report(prompt: str, analysis: str | None = None) -> Path:
    """Save report to reports/ directory."""
    REPORTS_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt_path = REPORTS_DIR / f"{today}_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    logger.info("Prompt saved: %s", prompt_path)

    if analysis:
        analysis_path = REPORTS_DIR / f"{today}_analysis.md"
        analysis_path.write_text(analysis, encoding="utf-8")
        logger.info("Analysis saved: %s", analysis_path)
        return analysis_path

    return prompt_path


def run_openclaw_analysis(prompt_path: Path) -> str | None:
    """Send prompt to OpenClaw (Claude Opus 4.6) for analysis."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt_path.read_text(encoding="utf-8")],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path.cwd()),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        logger.warning("OpenClaw returned code %d", result.returncode)
        if result.stderr:
            logger.warning("stderr: %s", result.stderr[:500])
        return None
    except FileNotFoundError:
        logger.error("'claude' CLI not found. Install Claude Code or check PATH.")
        return None
    except subprocess.TimeoutExpired:
        logger.error("OpenClaw analysis timed out (120s)")
        return None
    except Exception as e:
        logger.error("OpenClaw error: %s", e)
        return None


async def send_telegram_report(analysis: str, config: Config) -> None:
    """Send analysis summary to Telegram."""
    try:
        from telegram import Bot
        bot = Bot(token=config.telegram_bot_token)

        # Telegram has 4096 char limit, split if needed
        header = "📊 Daily AI Analysis Report\n\n"
        max_len = 4000 - len(header)

        if len(analysis) <= max_len:
            await bot.send_message(
                chat_id=config.telegram_chat_id,
                text=header + analysis,
            )
        else:
            # Send first chunk
            await bot.send_message(
                chat_id=config.telegram_chat_id,
                text=header + analysis[:max_len] + "\n\n(continua...)",
            )
            # Send remaining chunks
            remaining = analysis[max_len:]
            while remaining:
                chunk = remaining[:4000]
                remaining = remaining[4000:]
                await bot.send_message(
                    chat_id=config.telegram_chat_id,
                    text=chunk,
                )
        logger.info("Analysis sent to Telegram")
    except Exception as e:
        logger.error("Failed to send to Telegram: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Daily AI Analysis Pipeline")
    parser.add_argument("--days", type=int, default=1, help="Days of data to analyze")
    parser.add_argument("--analyze", action="store_true", help="Send to OpenClaw for analysis")
    parser.add_argument("--telegram", action="store_true", help="Also send results to Telegram")
    args = parser.parse_args()

    # Collect data
    logger.info("Collecting bot data (last %d days)...", args.days)
    data = collect_bot_data(args.days)

    if "error" in data:
        logger.error("Error: %s", data["error"])
        return

    summary = data["summary"]
    logger.info(
        "Data: %d positions, %d open, %d resolved, PnL: $%+.2f, Win rate: %.0f%%",
        summary["total_positions"],
        summary["open_positions"],
        summary["resolved"],
        summary["total_pnl"],
        summary["win_rate"] * 100,
    )

    # Generate prompt
    prompt = generate_report(data, args.days)
    saved = save_report(prompt)
    logger.info("Report prompt: %s (%d chars)", saved, len(prompt))

    # Print summary to console
    print(f"\n{'='*60}")
    print(f"  Daily Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")
    print(f"  Positions: {summary['total_positions']} total, {summary['open_positions']} open")
    print(f"  Resolved: {summary['resolved']} (W:{summary['wins']} L:{summary['losses']} TP:{summary['sold_take_profit']})")
    print(f"  Win rate: {summary['win_rate']:.0%}")
    print(f"  P&L: ${summary['total_pnl']:+.2f}")
    print(f"  Exposure: ${summary['current_exposure']:.2f}")
    print(f"\n  Trader Performance:")
    for name, stats in sorted(data["trader_performance"].items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = stats["won"] / (stats["won"] + stats["lost"]) if (stats["won"] + stats["lost"]) > 0 else 0
        print(f"    [{stats['tier']}] {name:25s} — PnL: ${stats['pnl']:+.2f} | W:{stats['won']} L:{stats['lost']} TP:{stats['sold']} | WR: {wr:.0%} | Open: {stats['open']}")
    print(f"{'='*60}")

    if args.analyze:
        logger.info("Sending to OpenClaw for analysis...")
        analysis = run_openclaw_analysis(saved)
        if analysis:
            save_report(prompt, analysis)
            print(f"\n{analysis}")

            if args.telegram:
                config = Config.load()
                asyncio.run(send_telegram_report(analysis, config))
        else:
            logger.error("Analysis failed. Prompt saved at: %s", saved)
            print(f"\nAnalysis failed. Run manually:")
            print(f"  claude -p \"$(cat {saved})\"")
    else:
        print(f"\nPrompt saved at: {saved}")
        print(f"Run analysis manually:")
        print(f"  claude -p \"$(cat {saved})\"")
        print(f"Or: python daily_report.py --analyze --telegram")


if __name__ == "__main__":
    main()
