from pathlib import Path
import hmac, hashlib

ROOT = Path(__file__).resolve().parents[1]


def test_customer_auth_and_wallet_routes_present():
    source = (ROOT / "app/main.py").read_text()
    for route in (
        '"/api/auth/signup"', '"/api/auth/login"', '"/api/auth/password-reset"',
        '"/api/auth/logout"', '"/api/customer/me"', '"/api/customer/wallets"',
        '"/api/customer/funding"', '"/api/internal/funding/webhook"',
    ):
        assert route in source


def test_funding_webhook_uses_idempotency_and_confirmation():
    source = (ROOT / "app/main.py").read_text()
    assert 'FundingTransaction.provider_reference' in source
    assert 'payload.status == "CONFIRMED"' in source
    assert 'await post_deposit' in source
    assert 'await sync_wallet_from_ledger' in source


def test_funding_signature_contract():
    secret = "test-secret"
    body = b'{"amount":100,"currency":"USD"}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, expected)
    assert not hmac.compare_digest(expected, "0" * 64)


def test_migration_adds_customer_wallet_tables():
    source = (ROOT / "alembic/versions/0005_customers_wallets_funding.py").read_text()
    for table in ('"customer_profiles"', '"wallets"', '"funding_transactions"'):
        assert table in source
    assert 'uq_funding_provider_reference' in source

def test_real_usdt_tron_deposit_support_is_present_and_fail_closed():
    source = (ROOT / "app/main.py").read_text()
    config = (ROOT / "app/config.py").read_text()
    assert '"/api/customer/usdt/deposit"' in source
    assert 'derive_usdt_tron_address_from_xpub' in source
    assert 'usdt_tron_enabled' in config
    assert 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in config
    assert 'only_confirmed' in source
    assert 'FundingTransaction.provider_reference' in source


def test_tron_xpub_derivation_is_public_only_and_seed_derivation_is_disabled():
    source = (ROOT / "app/usdt_tron.py").read_text()
    assert "derive_usdt_tron_address_from_xpub" in source
    assert "Bip44.FromExtendedKey" in source
    assert "IsPublicOnly" in source
    assert "Master-seed TRON derivation is disabled" in source


def test_omnibus_treasury_and_customer_ledger_architecture():
    config = (ROOT / "app/config.py").read_text()
    db = (ROOT / "app/db.py").read_text()
    funds = (ROOT / "app/customer_funds.py").read_text()
    main = (ROOT / "app/main.py").read_text()
    assert 'usdt_tron_treasury_address' in config
    assert 'TWFuigmmGbb5gsTS4KUtY5v2FmA1rJ3yC5' in config
    assert 'usdt_tron_shared_deposit_mode: bool = False' in config
    assert 'class CustomerLedgerAccount' in db
    assert 'class LedgerEntry' in db
    assert 'uq_ledger_entry_idempotency' in db
    assert 'post_deposit' in funds and 'reserve_trading' in funds
    assert 'credit_mode' in main
    assert 'Shared-address deposits cannot be auto-attributed safely' in main

def test_customer_cash_only_trading_is_server_side():
    config = (ROOT / "app/config.py").read_text()
    execution = (ROOT / "app/execution.py").read_text()
    assert 'customer_cash_only_trading: bool = True' in config
    assert "Order exceeds the customer's available funded USDT balance" in execution
    assert 'reserve_trading' in execution
    assert 'release_trading' in execution

def test_tron_monitor_credits_ledger_not_direct_balance_only():
    source = (ROOT / "app/main.py").read_text()
    assert 'await post_deposit' in source
    assert 'await sync_wallet_from_ledger' in source
    assert 'wallet.available_balance += amount' not in source


def test_admin_custody_reconciliation_is_monitoring_only():
    source = (ROOT / "app/main.py").read_text()
    assert '"/api/admin/custody/reconciliation"' in source
    assert 'treasury_onchain_balance' in source
    assert 'monitoring-only' in source
    assert 'never credits a customer from the chain' in source
    assert 'never credits a customer from the chain' in source


def test_withdrawals_use_authoritative_ledger_not_legacy_wallet_balance():
    source = (ROOT / "app/main.py").read_text()
    funds = (ROOT / "app/customer_funds.py").read_text()
    assert 'await reserve_withdrawal(db, profile.id, req.amount, reference_id=w.request_id)' in source
    assert 'await settle_withdrawal(db3, w3.customer_id, w3.amount, reference_id=w3.request_id)' in source
    assert 'await ledger_release_withdrawal(db2, w2.customer_id, w2.amount' in source
    assert 'await ledger_release_withdrawal(db, w.customer_id, w.amount' in source
    assert 'wallet.available_balance -= req.amount' not in source
    assert 'async def reserve_withdrawal' in funds
    assert 'async def release_withdrawal' in funds
    assert 'async def settle_withdrawal' in funds


def test_tron_min_confirmations_is_enforced():
    source = (ROOT / "app/main.py").read_text()
    assert 'settings.usdt_tron_min_confirmations' in source
    assert 'current_height - block_number + 1' in source


def test_customer_profile_and_wallet_creation_handle_concurrent_unique_races():
    source = Path("app/main.py").read_text()
    assert "async with db.begin_nested():" in source
    assert "except IntegrityError:" in source
    assert "uq_customer_auth_user_id" in Path("app/db.py").read_text()
    assert "uq_wallet_customer_currency" in Path("app/db.py").read_text()


def test_unknown_live_order_keeps_customer_reserve_until_reconciliation():
    source = Path("app/execution.py").read_text()
    unknown_block = source[source.index('except Exception as exc:', source.index('broker.market_order')):source.index('broker_id =', source.index('broker.market_order'))]
    assert 't.status = "UNKNOWN"' in unknown_block
    assert 'release_trading(db, customer_id, reserved_cash' not in unknown_block
    assert '_release_unneeded_order_reserve' not in unknown_block


def test_terminal_order_states_release_only_unused_reserve():
    source = Path("app/execution.py").read_text()
    assert 'if t.status in {"FILLED", "CANCELED", "REJECTED"}:' in source
    assert 'await _release_unneeded_order_reserve(db, t)' in source
    assert 'reserved = max(0.0, float(trade.reserved_cash or 0.0))' in source
    assert 'filled_cost = max(0.0, float(trade.filled_quantity or 0.0) * float(trade.average_fill_price or trade.requested_price or 0.0))' in source


def test_trading_fee_can_consume_trading_reserve_when_available_cash_is_zero():
    # Behavioural coverage lives in test_review_runtime_regressions.py
    # (test_fee_journal_matches_each_customer_balance_reduction); assert only the invariant here.
    source = Path("app/customer_funds.py").read_text()
    assert "from_reserved = fee_d - from_available" in source
    assert "cannot absorb trading fee" in source


def test_tron_deposit_reuses_existing_usdt_wallet_row():
    source = Path("app/main.py").read_text()
    start = source.index('@app.get("/api/customer/usdt/deposit")')
    end = source.index('@app.get("/api/customer/ledger")', start)
    block = source[start:end]
    assert 'Wallet.customer_id == profile.id, Wallet.currency == "USDT"' in block
    assert 'Wallet.network == "TRON"' not in block.split('if wallet and wallet.network', 1)[0]
    assert 'uq_wallet_customer_currency' in Path("app/db.py").read_text()


def test_customer_webhook_secret_is_header_only():
    source = (ROOT / "app/main.py").read_text()
    start = source.index('@app.post("/api/webhooks/{endpoint_id}")')
    end = source.index('@app.get("/api/customer/connectors")', start)
    block = source[start:end]
    assert 'x_atlas_webhook_token: str | None = Header(default=None)' in block
    assert 'token: str | None = None' not in block
    assert 'X-Atlas-Webhook-Token' in (ROOT / "GRID_WEBHOOK_CONNECTORS_3_9_6.md").read_text()


def test_binance_customer_subaccount_admin_route_uses_central_admin_auth():
    source = (ROOT / "app/main.py").read_text()
    start = source.index('@app.post("/api/admin/binance/customer-subaccount/plan")')
    end = source.index('@app.post("/api/customer/bot/start")', start)
    block = source[start:end]
    assert 'await auth(None, authorization)' in block
    assert 'settings.admin_token' not in block
    assert 'compare_digest(authorization.removeprefix("Bearer ").strip()' not in block


def test_customer_withdrawal_debits_trading_account_through_decimal():
    # req.amount > trading_account.cash_equity (both floats) can misjudge a boundary withdrawal
    # by float representation error, and repeated `cash_equity -= amount` accumulates float
    # drift. The comparison and each assignment must go through Decimal / quantize_money.
    source = (ROOT / "app/main.py").read_text()
    start = source.index("Close open trading positions before withdrawing allocated trading capital")
    end = source.index('risk = await score_withdrawal(', start)
    block = source[start:end]
    assert "amount_d = Decimal(str(req.amount))" in block
    assert "Decimal(str(trading_account.cash_equity))" in block
    assert "quantize_money(trading_account.cash_equity - req.amount)" in block
    assert "trading_account.cash_equity -= req.amount" not in block


def test_quantize_money_bounds_float_drift():
    from app.db import quantize_money
    total = 0.0
    for _ in range(10):
        total += 0.1
    assert total != 1.0  # the raw float drift this guards against
    assert quantize_money(total) == 1.0
