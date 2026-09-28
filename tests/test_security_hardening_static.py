from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sensitive_database_fields_use_authenticated_encryption():
    db = (ROOT / 'app/db.py').read_text()
    crypto = (ROOT / 'app/crypto.py').read_text()
    for field in ('detail: Mapped[str] = mapped_column(EncryptedText',
                  'destination: Mapped[str] = mapped_column(EncryptedText',
                  'deposit_address: Mapped[str] = mapped_column(EncryptedText',
                  'metadata_json: Mapped[str] = mapped_column(EncryptedText'):
        assert field in db
    assert 'Fernet' in crypto and 'InvalidToken' in crypto
    assert '_PREFIX = "enc:"' in crypto
    assert 'APP_ENCRYPTION_KEYS_JSON' in crypto
    assert 'APP_ENCRYPTION_ACTIVE_KEY_ID' in crypto


def test_otp_and_withdrawal_step_up_are_present():
    main = (ROOT / 'app/main.py').read_text()
    customer = (ROOT / 'app/templates/customer.html').read_text()
    assert '"/api/auth/otp/send"' in main
    assert '"/api/auth/otp/verify"' in main
    assert 'Fresh OTP step-up verification is required before withdrawal' in main
    assert 'X-Withdrawal-Step-Up' in customer


def test_production_requires_versioned_encryption_and_secret():
    main = (ROOT / 'app/main.py').read_text()
    crypto = (ROOT / 'app/crypto.py').read_text()
    assert 'validate_encryption_config' in main
    assert 'encryption_configured' in main
    assert 'secret_configured' in main
    assert 'APP_ENCRYPTION_KEYS_JSON' in crypto
    assert 'APP_ENCRYPTION_ACTIVE_KEY_ID' in crypto


def test_legacy_encryption_migration_exists():
    migration = (ROOT / 'alembic/versions/0008_encrypt_sensitive_data.py').read_text()
    script = (ROOT / 'scripts/encrypt_existing_data.py').read_text()
    assert '0008_encrypt_sensitive_data' in migration
    assert 'Encrypted ' in script


def test_withdrawal_stepup_tokens_are_single_use_and_persisted():
    main = (ROOT / 'app/main.py').read_text()
    db = (ROOT / 'app/db.py').read_text()
    migration = (ROOT / 'alembic/versions/0009_withdrawal_stepup_tokens.py').read_text()
    assert 'class WithdrawalStepUpToken(Base)' in db
    assert 'used_at.is_(None)' in main
    assert 'stepup.used_at = datetime.now(timezone.utc)' in main
    assert 'token_hash=hashlib.sha256(token.encode()).hexdigest()' in main
    assert '0009_withdrawal_stepup_tokens' in migration


def test_withdrawal_otp_send_is_bound_to_authenticated_contact():
    main = (ROOT / 'app/main.py').read_text()
    assert 'if purpose in {"withdrawal", "destination_verification"}:' in main
    assert '_otp_contact(user, req.email, req.phone)' in main
    assert '"create_user": False' in main


def test_customer_portal_requests_withdrawal_purpose_and_clears_stepup():
    customer = (ROOT / 'app/templates/customer.html').read_text()
    assert "purpose:'withdrawal'" in customer
    assert "sessionStorage.removeItem('atlas_withdrawal_step_up')" in customer


def test_google_authenticator_totp_mfa_is_native_supabase_and_mandatory():
    main = (ROOT / 'app/main.py').read_text()
    config = (ROOT / 'app/config.py').read_text()
    customer = (ROOT / 'app/templates/customer.html').read_text()
    assert 'customer_totp_required: bool = True' in config
    assert '"/api/auth/mfa/status"' in main
    assert '"/api/auth/mfa/enroll"' in main
    assert '"/api/auth/mfa/challenge"' in main
    assert '"/api/auth/mfa/verify"' in main
    assert '/auth/v1/factors' in main
    assert 'factor_type": "totp"' in main
    assert 'claims.get("aal", "aal1") != "aal2"' in main
    assert 'Google Authenticator' in customer


def test_withdrawal_requires_aal2_and_existing_stepup():
    main = (ROOT / 'app/main.py').read_text()
    start = main.index('@app.post("/api/customer/withdrawals")')
    block = main[start:start+5000]
    assert 'get_customer(authorization, db, require_aal2=True)' in block
    assert 'Fresh OTP step-up verification is required before withdrawal' in block


def test_admin_google_authenticator_is_required_in_production():
    main = (ROOT / 'app/main.py').read_text()
    config = (ROOT / 'app/config.py').read_text()
    assert 'admin_totp_required: bool = True' in config
    assert 'admin_supabase_user_ids: str = ""' in config
    assert '/api/admin/auth/login' in main
    assert '/api/admin/auth/mfa/status' in main
    assert '/api/admin/auth/mfa/enroll' in main
    assert '/api/admin/auth/mfa/challenge' in main
    assert '/api/admin/auth/mfa/verify' in main
    assert 'Google Authenticator verification required' in main
    assert 'Administrator account is not authorized' in main
    assert 'return await admin_claims(authorization, require_aal2=settings.admin_totp_required)' in main


def test_admin_sensitive_endpoints_accept_authorization_for_totp_session():
    main = (ROOT / 'app/main.py').read_text()
    for name in ('list_withdrawals', 'approve_withdrawal', 'release_withdrawal', 'review_withdrawal_risk', 'reconcile_withdrawal', 'reject_withdrawal'):
        start = main.index(f'async def {name}')
        block = main[start:main.index('\n\n', start)]
        assert 'authorization: str | None = Header(default=None)' in block
    assert 'await auth(x_admin_token, authorization)' in main
