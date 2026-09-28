from pathlib import Path

def test_withdrawal_controls_are_present():
    main = Path("app/main.py").read_text()
    db = Path("app/db.py").read_text()
    html = Path("app/templates/dashboard.html").read_text()
    assert "class Withdrawal(Base)" in db
    assert "/api/admin/withdrawals" in main
    assert "required_approvals" in main
    assert "A different administrator is required" in main
    assert "Withdrawal approvals" in html

def test_approval_does_not_directly_release_funds():
    main = Path("app/main.py").read_text()
    block = main[main.index('async def approve_withdrawal'):main.index('@app.post("/api/admin/withdrawals/{withdrawal_id}/reject")')]
    assert 'status = "APPROVED"' in block
    assert "execution_required" in block
    assert "market_order" not in block

def test_release_requires_separate_operator_and_whitelist():
    main = Path("app/main.py").read_text()
    security = Path("app/withdrawal_security.py").read_text()
    assert 'verify_release_operator(req.operator_id, x_release_token)' in main
    assert 'destination_allowed(w.destination, w.currency, w.network)' in main
    assert 'settings.local_signing_enabled' in main
    assert 'destination_fingerprint' in security

def test_withdrawal_create_persists_executable_fields():
    main = Path("app/main.py").read_text()
    block = main[main.index('async def create_withdrawal'):main.index('@app.post("/api/admin/withdrawals/{withdrawal_id}/approve")')]
    assert 'destination=req.destination or ""' in block
    assert 'destination_tag=req.destination_tag or ""' in block
    assert 'network=req.network or ""' in block
    assert 'w.proposal_digest = proposal_digest' in block


def test_release_requires_stored_proposal_digest():
    main = Path("app/main.py").read_text()
    block = main[main.index('async def release_withdrawal'):main.index('@app.post("/api/admin/withdrawals/{withdrawal_id}/proposal")')]
    assert 'if not w.proposal_digest:' in block
    assert 'hmac.compare_digest(w.proposal_digest, expected_digest)' in block


def test_model_path_sanitizes_all_user_controlled_components():
    main = Path("app/main.py").read_text()
    assert 're.sub(r"[^A-Za-z0-9_.-]+", "_", raw)' in main
    assert '_safe_model_component(req.exchange)' in main
    assert '_safe_model_component(req.symbol)' in main
    assert '_safe_model_component(req.timeframe)' in main

def test_withdrawal_list_supports_runtime_states_used_by_dashboard():
    main = Path("app/main.py").read_text()
    assert '"SUBMITTED"' in main and '"UNKNOWN"' in main and '"FAILED"' in main


def test_dashboard_escapes_untrusted_withdrawal_and_trade_fields():
    html = Path("app/templates/dashboard.html").read_text()
    assert "function esc(v)" in html
    assert "esc(x.request_id)" in html
    assert "esc(x.destination_masked)" in html
    assert "esc(x.symbol)" in html


def test_customer_withdrawal_is_reserved_and_requires_admin():
    main = Path("app/main.py").read_text()
    db = Path("app/db.py").read_text()
    customer = Path("app/templates/customer.html").read_text()
    assert 'class CustomerWithdrawalCreate' in main
    assert '/api/customer/withdrawals' in main
    assert 'await reserve_withdrawal(db, profile.id, req.amount, reference_id=w.request_id)' in main
    assert 'await sync_wallet_from_ledger(db, profile.id, "USDT")' in main
    assert 'required_approvals=2 if settings.withdrawal_dual_approval else 1' in main
    assert 'customer_id: Mapped[int | None]' in db
    assert 'Request withdrawal' in customer

def test_customer_withdrawal_releases_reserved_balance_on_reject_or_failure():
    main = Path("app/main.py").read_text()
    assert 'await ledger_release_withdrawal(db2, w2.customer_id, w2.amount, reference_id=w2.request_id + ":failed")' in main
    assert 'await ledger_release_withdrawal(db, w.customer_id, w.amount, reference_id=w.request_id + ":rejected")' in main

def test_tron_destination_validation_is_server_side():
    main = Path("app/main.py").read_text()
    assert 'TrxAddrDecoder.DecodeAddr' in main
    assert 'req.network.upper() != "TRON"' in main
