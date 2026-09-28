import os
import asyncio
import pytest

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_postgres_row_lock_concurrency():
    url = os.getenv("ATLAS_POSTGRES_URL", "").strip()
    if not url:
        pytest.skip("Set ATLAS_POSTGRES_URL to run PostgreSQL integration tests")
    asyncpg = pytest.importorskip("asyncpg")
    # Use asyncpg directly so this drill does not depend on Atlas application import order.
    if "postgresql" not in url:
        pytest.skip("ATLAS_POSTGRES_URL must target PostgreSQL")
    pool = await asyncpg.create_pool(url.replace("postgresql+asyncpg://", "postgresql://"), min_size=2, max_size=20)
    table = "atlas_concurrency_probe_31039"
    try:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
            await conn.execute(f"CREATE TABLE {table}(id integer PRIMARY KEY, balance numeric NOT NULL)")
            await conn.execute(f"INSERT INTO {table}(id,balance) VALUES(1,0)")

        async def worker():
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(f"SELECT balance FROM {table} WHERE id=1 FOR UPDATE")
                    await asyncio.sleep(0.001)
                    await conn.execute(f"UPDATE {table} SET balance=balance+1 WHERE id=1")
                    return row["balance"]

        await asyncio.gather(*[worker() for _ in range(100)])
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT balance FROM {table} WHERE id=1")
            assert float(row["balance"]) == 100.0
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await pool.close()
