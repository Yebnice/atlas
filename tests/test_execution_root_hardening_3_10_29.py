from pathlib import Path

def test_customer_reconciliation_uses_customer_broker():
    src = Path('app/execution.py').read_text()
    assert 'trade_customer_id is not None and not is_oanda' in src
    assert 'build_customer_binance_broker(' in src
    assert 'trade_broker.fetch_order' in src
    assert 'trade_broker.fetch_open_orders' in src

def test_exchange_validation_failure_releases_customer_reserve():
    src = Path('app/execution.py').read_text()
    assert 'The customer reserve was created before exchange-specific precision/limit' in src
    assert 'await _release_unneeded_order_reserve(db, t)' in src
    assert 't.status = "REJECTED"' in src
