"""Runtime regression coverage for accounting, proxy trust, and XML parsing fixes."""
import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.customer_funds import settle_realized_pnl, settle_trading_fee
from app.db import Base, CustomerLedgerAccount, Incident, LedgerJournal, LedgerJournalLine, TradingAccount
from app.main import _trusted_client_ip
from app.config import settings


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setattr(settings, "app_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "app_encryption_keys_json", "")
    monkeypatch.setattr(settings, "app_encryption_active_key_id", "v1")


async def with_database(check):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await check(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def test_models_create_and_financial_values_reload():
    async def check(sessions):
        async with sessions() as db:
            db.add(TradingAccount(customer_id=1, cash_equity=100.25))
            db.add(Incident(incident_key="test", summary="test incident"))
            await db.commit()
        async with sessions() as db:
            account = (await db.execute(select(TradingAccount))).scalar_one()
            # FinancialNumeric materializes floats so trading arithmetic (price * qty * 1.0015) works.
            assert isinstance(account.cash_equity, float)
            account.cash_equity -= 0.25
            assert account.cash_equity == pytest.approx(100.00)
            assert account.cash_equity * 1.0015 > 0
            incident = (await db.execute(select(Incident))).scalar_one()
            assert incident.opened_at is not None
    asyncio.run(with_database(check))


@pytest.mark.parametrize("available,reserved,fee", [("10", "0", "2"), ("1", "10", "3"), ("0", "10", "3")])
def test_fee_journal_matches_each_customer_balance_reduction(available, reserved, fee):
    async def check(sessions):
        async with sessions() as db:
            ledger = CustomerLedgerAccount(customer_id=1, available=Decimal(available), trading_reserved=Decimal(reserved))
            db.add(ledger)
            await db.commit()
            await settle_trading_fee(db, customer_id=1, fee=Decimal(fee), reference_id="fill:1")
            await db.commit()
        async with sessions() as db:
            ledger = (await db.execute(select(CustomerLedgerAccount))).scalar_one()
            lines = (await db.execute(select(LedgerJournalLine))).scalars().all()
            for bucket, before, after in [("AVAILABLE", Decimal(available), ledger.available), ("TRADING_RESERVED", Decimal(reserved), ledger.trading_reserved)]:
                change = sum((line.credit - line.debit for line in lines if line.account_code == f"LIABILITY:CUSTOMER:1:USDT:{bucket}"), Decimal(0))
                assert change == after - before
            assert sum(line.debit for line in lines) == sum(line.credit for line in lines) == Decimal(fee)
            before = (ledger.available, ledger.trading_reserved)
            await settle_trading_fee(db, customer_id=1, fee=Decimal(fee), reference_id="fill:1")
            await db.commit()
            assert (ledger.available, ledger.trading_reserved) == before
            assert len((await db.execute(select(LedgerJournal))).scalars().all()) == 1
    asyncio.run(with_database(check))


def test_loss_settlement_retry_does_not_require_funds_again():
    async def check(sessions):
        async with sessions() as db:
            db.add(CustomerLedgerAccount(customer_id=1, available=Decimal("10")))
            await db.commit()
            await settle_realized_pnl(db, customer_id=1, amount=-8, reference_id="close:1")
            await db.commit()
        async with sessions() as db:
            await settle_realized_pnl(db, customer_id=1, amount=-8, reference_id="close:1")
            await db.commit()
            ledger = (await db.execute(select(CustomerLedgerAccount))).scalar_one()
            assert ledger.available == Decimal("2")
            with pytest.raises(ValueError, match="cannot absorb"):
                await settle_realized_pnl(db, customer_id=1, amount=-8, reference_id="close:2")
    asyncio.run(with_database(check))


@pytest.mark.parametrize("peer,forwarded,expected", [
    ("198.51.100.8", "192.0.2.1", "198.51.100.8"),
    ("10.0.0.2", "192.0.2.1, 198.51.100.8", "198.51.100.8"),
    ("10.0.0.2", "192.0.2.1, 198.51.100.8, 10.0.0.3", "198.51.100.8"),
    ("10.0.0.2", "192.0.2.1, garbage", "10.0.0.2"),
    ("10.0.0.2", "192.0.2.1, , 10.0.0.3", "10.0.0.2"),
    ("10.0.0.2", "", "10.0.0.2"),
    ("::1", "2001:db8::10", "2001:db8::10"),
])
def test_proxy_chain_stops_at_nearest_untrusted_hop(monkeypatch, peer, forwarded, expected):
    monkeypatch.setattr(settings, "forwarded_allow_ips", "10.0.0.0/8,::1/128")
    request = Request({"type": "http", "client": (peer, 1234), "headers": [(b"x-forwarded-for", forwarded.encode())]})
    assert _trusted_client_ip(request) == expected


def test_executor_validation_returns_safe_error(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    def reject(*args, **kwargs):
        raise main.ExecutorValidationError("sensitive upstream details")

    monkeypatch.setattr(main, "build_executor_plan", reject)
    response = TestClient(main.app).post("/api/customer/executors", json={
        "kind": "TWAP", "asset": "crypto", "exchange": "binance",
        "symbol": "BTC/USDT", "side": "buy", "total_quantity": 1,
    })
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid executor configuration"}


def test_news_feed_rejects_xml_entities():
    from defusedxml.common import EntitiesForbidden
    from app.market_intelligence import _parse_rss
    payload = '<!DOCTYPE rss [<!ENTITY entity "injected">]><rss><item><title>&entity;</title></item></rss>'
    with pytest.raises(EntitiesForbidden):
        _parse_rss(payload, {"name": "test", "tier": "test"})
