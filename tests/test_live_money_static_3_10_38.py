from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'app/main.py').read_text()

def test_withdrawal_no_longer_auto_verifies_destination():
    block=MAIN[MAIN.index('@app.post("/api/customer/withdrawals")'):MAIN.index('@app.get("/api/customer/withdrawals")')]
    assert 'if not destination_policy["allowed"]:' in block
    assert 'verify_destination(db, customer_id=profile.id, fingerprint=destination_policy["fingerprint"])' not in block
    assert 'await register_or_check_destination' in block

def test_destination_verification_is_explicit_otp_purpose():
    assert 'destination_verification' in MAIN
    assert 'WITHDRAWAL_DESTINATION_VERIFIED' in MAIN

def test_live_admin_deriv_has_operations_role_gate():
    block=MAIN[MAIN.index('@app.post("/api/admin/deriv/execute")'):MAIN.index('@app.post("/api/admin/deriv/execute")')+900]
    assert 'require_role(claims, "OPERATIONS")' in block

def test_postgres_migration_repair_present():
    m=(ROOT/'alembic/versions/0033_live_money_hardening.py').read_text()
    assert 'ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)' in m
    assert 'incidents' in m
    assert 'destination_fingerprint' in m


def test_readyz_checks_new_production_safety_gates():
    assert 'migrations_current' in MAIN
    assert 'custody_signer_configured' in MAIN
    assert 'payout_boundary' in MAIN
    assert 'external_security_audit' in MAIN

def test_production_does_not_require_legacy_encryption_variable_only():
    assert 'APP_ENCRYPTION_KEY is required in production' not in MAIN
    assert 'validate_encryption_config' in MAIN

def test_direct_ccxt_withdrawals_are_non_production_only():
    payout=(ROOT/'app/payout.py').read_text()
    assert 'Direct CCXT withdrawals are disabled outside development' in payout
