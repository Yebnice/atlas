from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from fastapi import HTTPException
from .config import settings
from .db import WithdrawalDestination
from .withdrawal_security import destination_fingerprint

async def register_or_check_destination(db, *, customer_id: int, destination: str, currency: str, network: str, now: datetime | None = None) -> dict:
    """Return deterministic withdrawal destination policy state.

    Only a fingerprint is stored. New destinations enter a cooling-off period and must
    be explicitly verified before release. The withdrawal API never treats a newly seen
    address as trusted merely because a previous request was rejected.
    """
    now = now or datetime.now(timezone.utc)
    fp = destination_fingerprint(destination, currency, network)
    row = (await db.execute(select(WithdrawalDestination).where(
        WithdrawalDestination.customer_id == customer_id,
        WithdrawalDestination.fingerprint == fp,
    ).with_for_update())).scalar_one_or_none()
    if not row:
        row = WithdrawalDestination(
            customer_id=customer_id, fingerprint=fp, currency=currency.upper(),
            network=network.upper(), first_seen_at=now, status="PENDING",
        )
        db.add(row)
        await db.flush()
        return {"allowed": False, "reason": "new_destination_cooling_off", "fingerprint": fp, "ready_at": (now + timedelta(hours=max(0, settings.withdrawal_address_cooling_off_hours))).isoformat()}

    row.last_used_at = now
    if row.status == "VERIFIED":
        return {"allowed": True, "reason": "verified_destination", "fingerprint": fp}

    if not settings.withdrawal_new_address_requires_verification:
        if settings.environment in {"production", "staging"}:
            return {"allowed": False, "reason": "destination_verification_required_in_production", "fingerprint": fp}
        row.status = "VERIFIED"
        row.verified_at = now
        return {"allowed": True, "reason": "verification_disabled_development_only", "fingerprint": fp}

    ready_at = row.first_seen_at + timedelta(hours=max(0, settings.withdrawal_address_cooling_off_hours))
    if now < ready_at:
        return {"allowed": False, "reason": "new_destination_cooling_off", "fingerprint": fp, "ready_at": ready_at.isoformat()}
    return {"allowed": False, "reason": "destination_requires_verification", "fingerprint": fp, "ready_at": ready_at.isoformat()}

async def verify_destination(db, *, customer_id: int, fingerprint: str) -> None:
    row = (await db.execute(select(WithdrawalDestination).where(
        WithdrawalDestination.customer_id == customer_id,
        WithdrawalDestination.fingerprint == fingerprint,
    ).with_for_update())).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Withdrawal destination not found")
    now = datetime.now(timezone.utc)
    if now < row.first_seen_at + timedelta(hours=max(0, settings.withdrawal_address_cooling_off_hours)):
        raise HTTPException(409, "Destination cooling-off period has not elapsed")
    row.status = "VERIFIED"
    row.verified_at = now
