import asyncio
from sqlalchemy import text
from app.db import engine

COLUMNS = {
 "proposal_digest":"VARCHAR(64) DEFAULT ''",
 "execution_operator":"VARCHAR(120) DEFAULT ''",
 "execution_started_at":"DATETIME NULL",
 "reconciled_at":"DATETIME NULL",
 "local_signature":"TEXT DEFAULT ''",
}
async def main():
    async with engine.begin() as conn:
        for name, spec in COLUMNS.items():
            try:
                await conn.execute(text(f"ALTER TABLE withdrawals ADD COLUMN {name} {spec}"))
            except Exception as e:
                if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower(): raise
    print("Withdrawal v3 migration complete")
asyncio.run(main())
