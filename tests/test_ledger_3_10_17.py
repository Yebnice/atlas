from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_double_entry_models_and_migration():
    db=(ROOT/"app/db.py").read_text()
    mig=(ROOT/"alembic/versions/0019_double_entry_ledger.py").read_text()
    assert "class LedgerJournal(Base)" in db
    assert "class LedgerJournalLine(Base)" in db
    assert "uq_ledger_journal_idempotency" in db
    assert 'revision = "0019_double_entry_ledger"' in mig
    assert 'down_revision = "0018_customer_omnibus_ledger"' in mig

def test_balanced_journal_and_customer_accounting():
    funds=(ROOT/"app/customer_funds.py").read_text()
    assert "async def post_journal" in funds
    assert "total_debit != total_credit" in funds
    assert "ASSET:TRON:DEPOSIT" in funds
    assert "LIABILITY:CUSTOMER:" in funds
    assert "async def settle_realized_pnl" in funds
    assert "async def settle_trading_fee" in funds

def test_customer_ledger_statement_route():
    main=(ROOT/"app/main.py").read_text()
    assert '"/api/customer/ledger"' in main
    assert "ledger_statement" in main

def test_current_release_identity_without_changing_live_flags():
    config=(ROOT/"app/config.py").read_text()
    assert 'app_version: str = "3.10.45"' in config
    assert 'live_trading_enabled: bool = False' in config
    assert 'customer_live_trading_enabled: bool = False' in config
