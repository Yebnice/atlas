from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import HTTPException
from .config import settings
from .db import AdminRole, SessionLocal

ROLES = {"READ_ONLY", "OPERATIONS", "RISK_OFFICER", "TREASURY", "COMPLIANCE", "ADMINISTRATOR"}
ROLE_RANK = {
    "READ_ONLY": 10,
    "OPERATIONS": 20,
    "RISK_OFFICER": 30,
    "TREASURY": 30,
    "COMPLIANCE": 30,
    "ADMINISTRATOR": 100,
}

def _env_assignments() -> dict[str, str]:
    result: dict[str, str] = {}
    for item in str(settings.admin_role_assignments or "").split(","):
        if ":" not in item:
            continue
        uid, role = item.split(":", 1)
        uid, role = uid.strip(), role.strip().upper()
        if uid and role in ROLES:
            result[uid] = role
    return result

async def get_roles(auth_user_id: str) -> set[str]:
    uid = str(auth_user_id or "").strip()
    if not uid:
        return set()
    async with SessionLocal() as db:
        rows = (await db.execute(select(AdminRole.role).where(AdminRole.auth_user_id == uid, AdminRole.active.is_(True)))).all()
    roles = {str(r[0]).upper() for r in rows if str(r[0]).upper() in ROLES}
    if roles:
        return roles
    # Backward-compatible bootstrap: an explicitly allowlisted Supabase admin is ADMIN
    # until a database role is assigned. Once any role exists, the database is authoritative.
    allowed = {x.strip() for x in str(settings.admin_supabase_user_ids or "").split(",") if x.strip()}
    if uid in allowed:
        env_role = _env_assignments().get(uid, "ADMINISTRATOR")
        return {env_role}
    return set()

async def require_role(claims: dict, *required: str) -> str:
    if (claims or {}).get("auth_method") == "legacy_admin_token":
        return "ADMINISTRATOR"
    uid = str((claims or {}).get("sub") or "")
    roles = await get_roles(uid)
    required_norm = {r.upper() for r in required}
    if not roles:
        raise HTTPException(403, "Administrator role is not assigned")
    if "ADMINISTRATOR" in roles:
        return "ADMINISTRATOR"
    if not (roles & required_norm):
        raise HTTPException(403, f"Required administrator role: {', '.join(sorted(required_norm))}")
    return sorted(roles, key=lambda r: ROLE_RANK.get(r, 0), reverse=True)[0]

async def upsert_role(auth_user_id: str, role: str, active: bool = True) -> AdminRole:
    role = str(role).upper().strip()
    if role not in ROLES:
        raise ValueError(f"invalid admin role: {role}")
    async with SessionLocal() as db:
        row = (await db.execute(select(AdminRole).where(AdminRole.auth_user_id == auth_user_id, AdminRole.role == role))).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if not row:
            row = AdminRole(auth_user_id=auth_user_id, role=role, active=active, created_at=now, updated_at=now)
            db.add(row)
        else:
            row.active = active
            row.updated_at = now
        await db.commit()
        await db.refresh(row)
        return row
