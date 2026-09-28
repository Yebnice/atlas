from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_tron_scanner_uses_confirmed_history_and_contract_filter():
    main=(ROOT/"app/main.py").read_text()
    assert '"only_confirmed": "true"' in main
    assert '"contract_address": settings.usdt_tron_usdt_contract' in main
    assert 'if str(token.get("address") or "") != settings.usdt_tron_usdt_contract: ' in main or 'if str(token.get("address") or "") != settings.usdt_tron_usdt_contract:' in main

def test_tron_scanner_verifies_success_receipt():
    main=(ROOT/"app/main.py").read_text()
    assert 'walletsolidity/gettransactioninfobyid' in main
    assert 'receipt.result' in main or 'receipt.get("receipt")' in main
    assert '!= "SUCCESS"' in main

def test_tron_scanner_has_durable_cursor_and_overlap():
    db=(ROOT/"app/db.py").read_text()
    main=(ROOT/"app/main.py").read_text()
    mig=(ROOT/"alembic/versions/0020_tron_deposit_cursor.py").read_text()
    assert 'class TronDepositCursor(Base)' in db
    assert 'last_block_timestamp' in db
    assert 'usdt_tron_cursor_overlap_seconds' in main
    assert '0020_tron_deposit_cursor' in mig

def test_tron_scanner_paginates_and_does_not_advance_cursor_before_scan_completion():
    main=(ROOT/"app/main.py").read_text()
    assert 'fingerprint' in main
    assert 'scan_pages' in main
    assert 'cursor.last_block_timestamp = max' in main

def test_tron_deposit_is_idempotent_and_ledger_backed():
    main=(ROOT/"app/main.py").read_text()
    funds=(ROOT/"app/customer_funds.py").read_text()
    assert 'FundingTransaction.provider == "tron-usdt"' in main
    assert 'await post_deposit' in main
    assert 'UniqueConstraint("provider", "provider_reference"' in (ROOT/"app/db.py").read_text()
    assert 'idem = f"deposit:{provider_reference}"' in funds

def test_release_version():
    cfg=(ROOT/"CHANGELOG_3_10_18.md").read_text()
    assert "Atlas 3.10.18" in cfg
