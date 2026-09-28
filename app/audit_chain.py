from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import select
from .db import AuditChainState, AuditLog, SessionLocal

async def append_audit(db, *, event: str, detail: dict, actor_id: str = "") -> AuditLog:
    state = (await db.get(AuditChainState, 1))
    if not state:
        state = AuditChainState(id=1, last_hash="")
        db.add(state)
        await db.flush()
    # Row lock serializes hash-chain writers on PostgreSQL. SQLite remains deterministic for tests.
    state = (await db.execute(select(AuditChainState).where(AuditChainState.id == 1).with_for_update())).scalar_one()
    created = datetime.now(timezone.utc)
    previous = state.last_hash or ""
    payload = json.dumps({"event": event, "detail": detail, "actor_id": actor_id, "created_at": created.isoformat(), "previous_hash": previous}, sort_keys=True, separators=(",", ":"), default=str)
    event_hash = hashlib.sha256(payload.encode()).hexdigest()
    row = AuditLog(event=event, detail=json.dumps(detail, default=str), actor_id=actor_id, previous_hash=previous, event_hash=event_hash, created_at=created)
    db.add(row)
    state.last_hash = event_hash
    state.updated_at = created
    await db.commit()
    return row


async def record_audit(event: str, detail: dict, actor_id: str = "system") -> AuditLog:
    """Append an audit row using a dedicated session (safe to call from any module)."""
    async with SessionLocal() as db:
        return await append_audit(db, event=event, detail=detail, actor_id=actor_id)
