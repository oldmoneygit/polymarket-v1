"""Quick DB status check."""
import sqlite3
from pathlib import Path

db_path = Path("data/polymarket_bot.db")
if not db_path.exists():
    print("DB not found")
    exit()

db = sqlite3.connect(str(db_path))
c = db.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in c.fetchall()]
print(f"Tables: {tables}")

c.execute("SELECT COUNT(*) FROM seen_hashes")
print(f"Seen hashes: {c.fetchone()[0]}")

c.execute("SELECT COUNT(*) FROM positions")
pos_count = c.fetchone()[0]
print(f"Simulated positions: {pos_count}")

if pos_count > 0:
    print("\nLatest positions:")
    c.execute("""
        SELECT market_title, side, outcome, entry_price, usdc_invested, 
               trader_copied, status, dry_run, opened_at
        FROM positions ORDER BY opened_at DESC LIMIT 15
    """)
    for row in c.fetchall():
        title = row[0][:45] if row[0] else "?"
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(row[8], tz=timezone.utc).strftime("%H:%M") if row[8] else "?"
        print(f"  [{ts}] {title} | {row[1]} {row[2]} @ ${row[3]:.2f} | ${row[4]:.2f} | {row[5][:12]}... | {row[6]}")

c.execute("SELECT key, value FROM bot_state")
states = c.fetchall()
if states:
    print(f"\nBot state: {dict(states)}")

# Daily PnL
c.execute("SELECT SUM(pnl) FROM positions WHERE status != 'open' AND pnl IS NOT NULL")
pnl = c.fetchone()[0]
print(f"\nRealized P&L: ${pnl:.2f}" if pnl else "\nRealized P&L: $0.00 (no resolved positions yet)")

db.close()
