"""End-to-end paper order through execute_signal: catches NameErrors and Decimal/float TypeErrors."""
import asyncio
import os
import uuid

os.environ.setdefault("ENVIRONMENT", "development")

import pytest
from sqlalchemy import select


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    from cryptography.fernet import Fernet
    from app.config import settings
    monkeypatch.setattr(settings, "app_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "app_encryption_keys_json", "")
    monkeypatch.setattr(settings, "app_encryption_active_key_id", "v1")
    monkeypatch.setattr(settings, "discipline_entry_cooldown_seconds", 0)


def test_paper_buy_then_sell_round_trip():
    from app import execution
    from app.db import init_db, SessionLocal, Trade, Position, AuditLog

    sym = f"BTC/USDT"
    ts = uuid.uuid4().hex  # unique signal timestamp => unique idempotent client order id

    async def run():
        await init_db()
        buy = await execution.execute_signal(sym, "buy", 0.01, 50000.0, {"score": 0.9}, "binance", "1h",
                                             f"{ts}-b", force_paper=True, stop_loss_price=49000.0, take_profit_price=52000.0)
        assert buy, buy
        sell = await execution.execute_signal(sym, "sell", 0.01, 50500.0, {"score": 0.9}, "binance", "1h",
                                              f"{ts}-s", force_paper=True, stop_loss_price=51500.0, take_profit_price=49000.0)
        assert sell, sell
        async with SessionLocal() as db:
            trades = (await db.execute(select(Trade).where(Trade.client_order_id.like("ait-%")))).scalars().all()
            assert trades
            assert all(isinstance(t.filled_quantity, float) and isinstance(t.requested_price, float) for t in trades)
            audits = (await db.execute(select(AuditLog).where(AuditLog.event == "PAPER_ORDER"))).scalars().all()
            assert audits

    asyncio.run(run())
