#!/usr/bin/env python3
"""Encrypt legacy plaintext sensitive database values in-place.

Run after Alembic migration 0008 and with APP_ENCRYPTION_KEY loaded from the
production Secret Manager. The ORM encrypts on write and transparently decrypts
on read. This script touches only rows that are currently plaintext.
"""
import asyncio
from sqlalchemy import select
from app.db import SessionLocal, AuditLog, Withdrawal, CustomerProfile, Wallet, FundingTransaction

MODELS = (AuditLog, Withdrawal, CustomerProfile, Wallet, FundingTransaction)


def fields(obj):
    if isinstance(obj, AuditLog): return ("detail",)
    if isinstance(obj, Withdrawal): return ("destination", "destination_tag", "provider_error", "rejection_reason", "local_signature")
    if isinstance(obj, CustomerProfile): return ("email", "display_name")
    if isinstance(obj, Wallet): return ("deposit_address", "token_contract")
    return ("metadata_json",)


async def main():
    changed = 0
    async with SessionLocal() as db:
        for model in MODELS:
            rows = (await db.execute(select(model))).scalars().all()
            for row in rows:
                # Reading uses the encrypted type. A plaintext legacy value is returned
                # unchanged; assigning it back triggers authenticated encryption on bind.
                for field in fields(row):
                    value = getattr(row, field)
                    if value and not str(value).startswith("enc:v1:"):
                        setattr(row, field, value)
                        changed += 1
        await db.commit()
    print(f"Encrypted {changed} legacy field values.")


if __name__ == "__main__":
    asyncio.run(main())
