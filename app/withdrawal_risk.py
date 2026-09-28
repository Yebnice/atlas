from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, case
from .db import Withdrawal
from .config import settings

async def score_withdrawal(db, *, customer_id: int, wallet_balance: float, amount: float, destination: str, currency: str, network: str) -> dict:
    now = datetime.now(timezone.utc)
    since24 = now - timedelta(hours=24)
    since7 = now - timedelta(days=7)
    # Aggregate directly in SQL; do not cap the input set at 100 records.
    totals = await db.execute(select(
        func.coalesce(func.sum(case((Withdrawal.created_at >= since24, Withdrawal.amount), else_=0)), 0),
        func.coalesce(func.sum(Withdrawal.amount), 0),
        func.coalesce(func.sum(case((Withdrawal.created_at >= since24, case((Withdrawal.status == "UNKNOWN", 1), else_=0)), else_=0)), 0),
    ).where(
        Withdrawal.customer_id == customer_id,
        Withdrawal.created_at >= since7,
        Withdrawal.status != "REJECTED",
    ))
    total24, total7, unknown24 = totals.one()
    total24 = float(total24 or 0)
    total7 = float(total7 or 0)
    unknown24 = int(unknown24 or 0)

    # Destination is encrypted at rest, so compare decrypted values without imposing a 100-row cap.
    rows = (await db.execute(select(Withdrawal.destination).where(
        Withdrawal.customer_id == customer_id,
        Withdrawal.created_at >= since7,
        Withdrawal.destination.is_not(None),
    ))).scalars().all()
    known_destination = any((d or "").strip() == destination.strip() for d in rows)

    score = 0.0
    flags: list[str] = []
    ratio = amount / wallet_balance if wallet_balance > 0 else 1.0
    if not known_destination:
        score += 0.30; flags.append("NEW_DESTINATION")
    if ratio >= settings.withdrawal_balance_ratio_block:
        score += 0.45; flags.append("HIGH_BALANCE_RATIO")
    elif ratio >= settings.withdrawal_balance_ratio_review:
        score += 0.25; flags.append("ELEVATED_BALANCE_RATIO")
    if total24 + amount > settings.withdrawal_velocity_24h:
        score += 0.35; flags.append("24H_VELOCITY_LIMIT")
    elif total24 + amount > settings.withdrawal_velocity_24h * 0.75:
        score += 0.15; flags.append("24H_VELOCITY_ELEVATED")
    if total7 + amount > settings.withdrawal_velocity_7d:
        score += 0.25; flags.append("7D_VELOCITY_LIMIT")
    if unknown24 >= settings.withdrawal_max_unknown_24h:
        score += 0.20; flags.append("RECENT_UNKNOWN_PAYOUTS")
    if amount >= settings.withdrawal_max_amount * 0.8:
        score += 0.10; flags.append("NEAR_MAX_AMOUNT")
    if currency.upper() != "USDT" or network.upper() != "TRON":
        score += 0.20; flags.append("UNEXPECTED_ASSET_NETWORK")
    score = min(1.0, round(score, 4))
    decision = "BLOCK" if score >= settings.withdrawal_block_score else ("REVIEW" if score >= settings.withdrawal_review_score else "ALLOW")
    return {"score": score, "flags": flags, "decision": decision, "velocity_24h": total24, "velocity_7d": total7, "balance_ratio": round(ratio, 4), "known_destination": known_destination}
