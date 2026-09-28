from __future__ import annotations
import json
from datetime import datetime, timezone
from sqlalchemy import select
from .db import Incident, SessionLocal

async def open_incident(*, key: str, severity: str, category: str, summary: str, detail: dict, customer_id: int | None = None) -> int | None:
    async with SessionLocal() as db:
        row = (await db.execute(select(Incident).where(Incident.incident_key == key).with_for_update())).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row:
            if row.status == "RESOLVED":
                row.status = "OPEN"
                row.resolved_at = None
                row.resolved_by = ""
            row.severity = severity
            row.category = category
            row.summary = summary[:500]
            row.detail_json = json.dumps(detail, default=str)
            row.updated_at = now
        else:
            row = Incident(incident_key=key, severity=severity, status="OPEN", category=category, customer_id=customer_id, summary=summary[:500], detail_json=json.dumps(detail, default=str), opened_at=now, updated_at=now)
            db.add(row)
        await db.commit()
        return row.id

async def resolve_incident(key: str, actor_id: str = "") -> bool:
    async with SessionLocal() as db:
        row = (await db.execute(select(Incident).where(Incident.incident_key == key).with_for_update())).scalar_one_or_none()
        if not row:
            return False
        row.status = "RESOLVED"; row.resolved_at = datetime.now(timezone.utc); row.resolved_by = actor_id[:160]
        await db.commit()
        return True
