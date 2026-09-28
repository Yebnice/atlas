#!/usr/bin/env python3
"""Best-effort migration for the shipped v2 SQLite schema into v3. Back up the DB first."""
import sqlite3, sys
from pathlib import Path

path=Path(sys.argv[1] if len(sys.argv)>1 else "data/trading.db")
if not path.exists(): raise SystemExit(f"Database not found: {path}")
backup=path.with_suffix(path.suffix+".bak")
backup.write_bytes(path.read_bytes())
conn=sqlite3.connect(path)
cur=conn.cursor()

def cols(table): return {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}

if "trades" in [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
    c=cols("trades")
    adds={
      "signal_id":"TEXT NOT NULL DEFAULT ''", "exchange":"TEXT NOT NULL DEFAULT ''", "timeframe":"TEXT NOT NULL DEFAULT ''",
      "filled_quantity":"REAL NOT NULL DEFAULT 0", "remaining_quantity":"REAL NOT NULL DEFAULT 0",
      "requested_price":"REAL NOT NULL DEFAULT 0", "fee":"REAL NOT NULL DEFAULT 0", "notional":"REAL NOT NULL DEFAULT 0",
      "stop_loss_price":"REAL NOT NULL DEFAULT 0", "take_profit_price":"REAL NOT NULL DEFAULT 0"
    }
    for name, ddl in adds.items():
        if name not in c: cur.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")
    cur.execute("UPDATE trades SET signal_id=CASE WHEN signal_id='' THEN client_order_id ELSE signal_id END")
    cur.execute("UPDATE trades SET exchange=CASE WHEN exchange='' THEN 'unknown' ELSE exchange END")
    cur.execute("UPDATE trades SET filled_quantity=quantity WHERE filled_quantity=0 AND status IN ('FILLED','SIMULATED')")
    cur.execute("UPDATE trades SET remaining_quantity=MAX(requested_quantity-filled_quantity,0)")

cur.execute("CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY AUTOINCREMENT, exchange TEXT NOT NULL DEFAULT '', symbol TEXT NOT NULL, quantity REAL NOT NULL DEFAULT 0, average_entry_price REAL NOT NULL DEFAULT 0, mark_price REAL NOT NULL DEFAULT 0, realized_pnl REAL NOT NULL DEFAULT 0, unrealized_pnl REAL NOT NULL DEFAULT 0, updated_at DATETIME)")
cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_position_symbol ON positions(symbol)")
cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_signal_id ON trades(signal_id)")
cur.execute("CREATE INDEX IF NOT EXISTS ix_trade_status_symbol ON trades(status,symbol)")
cur.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at DATETIME)")
conn.commit(); conn.close()
print(f"Migrated {path}; backup at {backup}")
