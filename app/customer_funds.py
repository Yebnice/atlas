from __future__ import annotations
from decimal import Decimal
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import CustomerLedgerAccount, LedgerEntry, LedgerJournal, LedgerJournalLine, Wallet, TradingAccount, utcnow

USDT = "USDT"
D = Decimal

async def get_or_create_ledger(db, customer_id: int, currency: str = USDT) -> CustomerLedgerAccount:
    row = (await db.execute(select(CustomerLedgerAccount).where(
        CustomerLedgerAccount.customer_id == customer_id,
        CustomerLedgerAccount.currency == currency,
    ).with_for_update())).scalar_one_or_none()
    if row:
        return row
    # Concurrent first-use requests can both observe no ledger row. Keep the
    # uniqueness race inside a savepoint, then reuse the committed winner.
    try:
        async with db.begin_nested():
            row = CustomerLedgerAccount(customer_id=customer_id, currency=currency)
            db.add(row)
            await db.flush()
    except IntegrityError:
        row = (await db.execute(select(CustomerLedgerAccount).where(
            CustomerLedgerAccount.customer_id == customer_id,
            CustomerLedgerAccount.currency == currency,
        ).with_for_update())).scalar_one_or_none()
        if not row:
            raise
        return row
    # One-time migration of legacy wallet balance into the authoritative ledger.
    wallet = (await db.execute(select(Wallet).where(Wallet.customer_id == customer_id, Wallet.currency == currency).with_for_update())).scalar_one_or_none()
    if wallet and float(wallet.available_balance or 0) > 0:
        row.available = D(str(wallet.available_balance))
        row.trading_reserved = 0
        row.withdrawal_reserved = 0
    return row

async def post_journal(db, *, currency: str, entry_type: str, reference_type: str, reference_id: str, idempotency_key: str, lines: list[dict], description: str = "") -> LedgerJournal:
    """Create an immutable balanced double-entry journal. All amounts are Decimal-safe."""
    existing = (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idempotency_key))).scalar_one_or_none()
    if existing:
        return existing
    total_debit = sum((D(str(line.get("debit", 0))) for line in lines), D("0"))
    total_credit = sum((D(str(line.get("credit", 0))) for line in lines), D("0"))
    if total_debit != total_credit:
        raise ValueError("ledger journal is not balanced")
    if total_debit <= 0:
        raise ValueError("ledger journal must contain a positive amount")
    journal = LedgerJournal(currency=currency, entry_type=entry_type, reference_type=reference_type,
                            reference_id=reference_id, idempotency_key=idempotency_key, description=description)
    db.add(journal)
    await db.flush()
    for idx, line in enumerate(lines, start=1):
        debit = D(str(line.get("debit", 0)))
        credit = D(str(line.get("credit", 0)))
        if debit < 0 or credit < 0 or (debit > 0 and credit > 0):
            raise ValueError("journal line must contain either debit or credit")
        db.add(LedgerJournalLine(journal_id=journal.id, line_no=idx, account_code=str(line["account_code"]),
                                 customer_id=line.get("customer_id"), currency=currency, debit=debit, credit=credit))
    return journal


def _customer_account(customer_id: int, bucket: str, currency: str = USDT) -> str:
    return f"LIABILITY:CUSTOMER:{customer_id}:{currency}:{bucket}"


async def post_deposit(db, *, customer_id: int, wallet_id: int, amount: float, provider_reference: str, metadata: dict) -> CustomerLedgerAccount:
    amount_d = D(str(amount))
    if amount_d <= 0:
        raise ValueError("deposit amount must be positive")
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"deposit:{provider_reference}"
    existing = (await db.execute(select(LedgerEntry).where(LedgerEntry.idempotency_key == idem))).scalar_one_or_none()
    if existing:
        return ledger
    ledger.available = D(str(ledger.available)) + amount_d
    await post_journal(db, currency=USDT, entry_type="DEPOSIT_CREDIT", reference_type="TRON_TX",
                       reference_id=provider_reference, idempotency_key=idem,
                       lines=[
                           {"account_code": f"ASSET:TRON:DEPOSIT:{wallet_id}", "debit": amount_d, "credit": 0},
                           {"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": 0, "credit": amount_d},
                       ], description="Confirmed customer USDT deposit")
    db.add(LedgerEntry(customer_id=customer_id, currency=USDT, entry_type="DEPOSIT_CREDIT",
                       debit=0, credit=amount_d, amount=amount_d, reference_type="TRON_TX",
                       reference_id=provider_reference, idempotency_key=idem,
                       metadata_json=json.dumps({"wallet_id": wallet_id, **metadata}, separators=(",", ":"))))
    return ledger

async def sync_wallet_from_ledger(db, customer_id: int, currency: str = USDT) -> None:
    ledger = await get_or_create_ledger(db, customer_id, currency)
    wallet = (await db.execute(select(Wallet).where(Wallet.customer_id == customer_id, Wallet.currency == currency).with_for_update())).scalar_one_or_none()
    if wallet:
        wallet.available_balance = float(ledger.available)
        wallet.locked_balance = float(ledger.trading_reserved + ledger.withdrawal_reserved)
        wallet.updated_at = utcnow()

async def reserve_trading(db, customer_id: int, amount: float, *, reference_id: str) -> CustomerLedgerAccount:
    """Reserve customer cash for trading.

    ``reference_id`` must be stable across retries of the same logical reservation
    (e.g. derived from a trade id and fill count) so that a duplicate call -- caused
    by a client retry, a transaction retry, or duplicate event delivery -- is
    recognized by post_journal()'s idempotency check instead of reserving the
    customer's cash a second time.
    """
    amount_d = D(str(amount))
    if amount_d <= 0:
        raise ValueError("reserve amount must be positive")
    reference_id = str(reference_id or "").strip()
    if not reference_id:
        raise ValueError("reserve_trading requires a stable reference_id")
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"reserve:{reference_id}"
    if (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idem))).scalar_one_or_none():
        return ledger
    if D(str(ledger.available)) < amount_d:
        raise ValueError("insufficient available customer balance")
    ledger.available = D(str(ledger.available)) - amount_d
    ledger.trading_reserved = D(str(ledger.trading_reserved)) + amount_d
    await post_journal(db, currency=USDT, entry_type="TRADING_RESERVE", reference_type="TRADING",
                       reference_id=reference_id, idempotency_key=idem,
                       lines=[
                           {"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": amount_d, "credit": 0},
                           {"account_code": _customer_account(customer_id, "TRADING_RESERVED"), "customer_id": customer_id, "debit": 0, "credit": amount_d},
                       ], description="Reserve customer cash for trading")
    db.add(LedgerEntry(customer_id=customer_id, currency=USDT, entry_type="TRADING_RESERVE",
                       debit=amount_d, credit=0, amount=amount_d, reference_type="TRADING",
                       reference_id=reference_id, idempotency_key=idem))
    return ledger

async def release_trading(db, customer_id: int, amount: float, *, reference_id: str) -> CustomerLedgerAccount:
    amount_d = D(str(amount))
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"release:{reference_id}:{customer_id}"
    if (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idem))).scalar_one_or_none():
        return ledger
    release = min(amount_d, D(str(ledger.trading_reserved)))
    if release <= 0:
        return ledger
    ledger.trading_reserved = D(str(ledger.trading_reserved)) - release
    ledger.available = D(str(ledger.available)) + release
    await post_journal(db, currency=USDT, entry_type="TRADING_RELEASE", reference_type="TRADE",
                       reference_id=reference_id, idempotency_key=idem,
                       lines=[
                           {"account_code": _customer_account(customer_id, "TRADING_RESERVED"), "customer_id": customer_id, "debit": release, "credit": 0},
                           {"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": 0, "credit": release},
                       ], description="Release unused customer trading reserve")
    db.add(LedgerEntry(customer_id=customer_id, currency=USDT, entry_type="TRADING_RELEASE",
                       debit=0, credit=release, amount=release, reference_type="TRADE",
                       reference_id=reference_id, idempotency_key=idem))
    return ledger

async def reserve_withdrawal(db, customer_id: int, amount: float, *, reference_id: str) -> CustomerLedgerAccount:
    amount_d = D(str(amount))
    if amount_d <= 0:
        raise ValueError("withdrawal reserve amount must be positive")
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"withdrawal-reserve:{reference_id}"
    if (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idem))).scalar_one_or_none():
        return ledger
    if D(str(ledger.available)) < amount_d:
        raise ValueError("insufficient available customer balance")
    ledger.available = D(str(ledger.available)) - amount_d
    ledger.withdrawal_reserved = D(str(ledger.withdrawal_reserved)) + amount_d
    await post_journal(db, currency=USDT, entry_type="WITHDRAWAL_RESERVE", reference_type="WITHDRAWAL",
                       reference_id=reference_id, idempotency_key=idem,
                       lines=[
                           {"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": amount_d, "credit": 0},
                           {"account_code": _customer_account(customer_id, "WITHDRAWAL_RESERVED"), "customer_id": customer_id, "debit": 0, "credit": amount_d},
                       ], description="Reserve customer cash for withdrawal")
    db.add(LedgerEntry(customer_id=customer_id, currency=USDT, entry_type="WITHDRAWAL_RESERVE",
                       debit=amount_d, credit=0, amount=amount_d, reference_type="WITHDRAWAL",
                       reference_id=reference_id, idempotency_key=idem))
    return ledger

async def release_withdrawal(db, customer_id: int, amount: float, *, reference_id: str) -> CustomerLedgerAccount:
    amount_d = D(str(amount))
    if amount_d <= 0:
        raise ValueError("withdrawal release amount must be positive")
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"withdrawal-release:{reference_id}"
    if (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idem))).scalar_one_or_none():
        return ledger
    release = min(amount_d, D(str(ledger.withdrawal_reserved)))
    if release <= 0:
        return ledger
    ledger.withdrawal_reserved = D(str(ledger.withdrawal_reserved)) - release
    ledger.available = D(str(ledger.available)) + release
    await post_journal(db, currency=USDT, entry_type="WITHDRAWAL_RELEASE", reference_type="WITHDRAWAL",
                       reference_id=reference_id, idempotency_key=idem,
                       lines=[
                           {"account_code": _customer_account(customer_id, "WITHDRAWAL_RESERVED"), "customer_id": customer_id, "debit": release, "credit": 0},
                           {"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": 0, "credit": release},
                       ], description="Release failed or rejected customer withdrawal reserve")
    db.add(LedgerEntry(customer_id=customer_id, currency=USDT, entry_type="WITHDRAWAL_RELEASE",
                       debit=0, credit=release, amount=release, reference_type="WITHDRAWAL",
                       reference_id=reference_id, idempotency_key=idem))
    return ledger

async def settle_withdrawal(db, customer_id: int, amount: float, *, reference_id: str) -> CustomerLedgerAccount:
    amount_d = D(str(amount))
    if amount_d <= 0:
        raise ValueError("withdrawal settlement amount must be positive")
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"withdrawal-settlement:{reference_id}"
    if (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idem))).scalar_one_or_none():
        return ledger
    settle = min(amount_d, D(str(ledger.withdrawal_reserved)))
    if settle <= 0:
        return ledger
    ledger.withdrawal_reserved = D(str(ledger.withdrawal_reserved)) - settle
    await post_journal(db, currency=USDT, entry_type="WITHDRAWAL_SETTLEMENT", reference_type="WITHDRAWAL",
                       reference_id=reference_id, idempotency_key=idem,
                       lines=[
                           {"account_code": _customer_account(customer_id, "WITHDRAWAL_RESERVED"), "customer_id": customer_id, "debit": settle, "credit": 0},
                           {"account_code": "ASSET:TRON:WITHDRAWAL", "debit": 0, "credit": settle},
                       ], description="Settle completed customer withdrawal")
    db.add(LedgerEntry(customer_id=customer_id, currency=USDT, entry_type="WITHDRAWAL_SETTLEMENT",
                       debit=settle, credit=0, amount=settle, reference_type="WITHDRAWAL",
                       reference_id=reference_id, idempotency_key=idem))
    return ledger

async def customer_balance(db, customer_id: int, currency: str = USDT) -> dict:
    ledger = await get_or_create_ledger(db, customer_id, currency)
    return {"available": float(ledger.available), "trading_reserved": float(ledger.trading_reserved),
            "withdrawal_reserved": float(ledger.withdrawal_reserved),
            "total": float(D(str(ledger.available)) + D(str(ledger.trading_reserved)) + D(str(ledger.withdrawal_reserved)))}


async def settle_realized_pnl(db, *, customer_id: int, amount: float, reference_id: str) -> None:
    """Post realized USDT P&L into the customer liability ledger exactly once."""
    pnl = D(str(amount))
    if pnl == 0:
        return
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"settlement:{reference_id}"
    if (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idem))).scalar_one_or_none():
        return
    if pnl < 0 and D(str(ledger.available)) < abs(pnl):
        raise ValueError("customer ledger cannot absorb realized trading loss")
    if pnl > 0:
        lines = [
            {"account_code": "ASSET:TRADING:SETTLEMENT", "debit": pnl, "credit": 0},
            {"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": 0, "credit": pnl},
        ]
    else:
        loss = abs(pnl)
        lines = [
            {"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": loss, "credit": 0},
            {"account_code": "ASSET:TRADING:SETTLEMENT", "debit": 0, "credit": loss},
        ]
    await post_journal(db, currency=USDT, entry_type="TRADE_SETTLEMENT", reference_type="TRADE",
                       reference_id=reference_id, idempotency_key=idem, lines=lines,
                       description="Realized trading P&L settlement")
    ledger.available = D(str(ledger.available)) + pnl


async def settle_trading_fee(db, *, customer_id: int, fee: float, reference_id: str) -> None:
    fee_d = D(str(fee))
    if fee_d <= 0:
        return
    ledger = await get_or_create_ledger(db, customer_id, USDT)
    idem = f"fee:{reference_id}"
    if (await db.execute(select(LedgerJournal).where(LedgerJournal.idempotency_key == idem))).scalar_one_or_none():
        return
    available = D(str(ledger.available))
    reserved = D(str(ledger.trading_reserved))
    if available + reserved < fee_d:
        raise ValueError("customer ledger cannot absorb trading fee")
    from_available = min(available, fee_d)
    from_reserved = fee_d - from_available
    ledger.available = available - from_available
    ledger.trading_reserved = reserved - from_reserved
    # A fee reduces customer liability (debit) and is recognised on the fee account (credit).
    lines = []
    if from_available > 0:
        lines.append({"account_code": _customer_account(customer_id, "AVAILABLE"), "customer_id": customer_id, "debit": from_available, "credit": 0})
    if from_reserved > 0:
        lines.append({"account_code": _customer_account(customer_id, "TRADING_RESERVED"), "customer_id": customer_id, "debit": from_reserved, "credit": 0})
    lines.append({"account_code": "EXPENSE:TRADING_FEES", "debit": 0, "credit": fee_d})
    await post_journal(db, currency=USDT, entry_type="TRADING_FEE", reference_type="TRADE",
                       reference_id=reference_id, idempotency_key=idem, lines=lines,
                       description="Trading fee attribution")


async def ledger_statement(db, customer_id: int, currency: str = USDT, limit: int = 100) -> list[dict]:
    rows = (await db.execute(select(LedgerJournal, LedgerJournalLine).join(
        LedgerJournalLine, LedgerJournalLine.journal_id == LedgerJournal.id
    ).where(LedgerJournalLine.customer_id == customer_id, LedgerJournal.currency == currency)
      .order_by(LedgerJournal.created_at.desc(), LedgerJournalLine.line_no).limit(limit))).all()
    return [{"journal_id": j.id, "entry_type": j.entry_type, "reference_type": j.reference_type,
             "reference_id": j.reference_id, "account_code": line.account_code,
             "debit": float(line.debit), "credit": float(line.credit),
             "created_at": j.created_at.isoformat() if j.created_at else None} for j, line in rows]
