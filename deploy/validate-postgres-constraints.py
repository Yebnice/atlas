"""Validate all NOT VALID PostgreSQL foreign keys after orphan cleanup."""
import os, asyncio
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    url=os.environ.get("DATABASE_URL","")
    if not url.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must point to PostgreSQL")
    engine=create_async_engine(url,connect_args={"statement_cache_size":0})
    async with engine.begin() as conn:
        rows=(await conn.exec_driver_sql("""SELECT conrelid::regclass::text AS table_name, conname FROM pg_constraint WHERE contype='f' AND NOT convalidated ORDER BY conrelid::regclass::text, conname""")).all()
        if not rows:
            print("No NOT VALID foreign keys found")
        for table,name in rows:
            print(f"Validating {table}.{name}")
            await conn.exec_driver_sql(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{name}"')
    await engine.dispose()
    print("All foreign keys validated")

if __name__ == "__main__": asyncio.run(main())
