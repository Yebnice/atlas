from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]


def test_money_columns_are_numeric_storage_not_float():
    import re
    source = (ROOT / "app/db.py").read_text()
    targets = {
        "AppState": ["cash_equity","equity","peak_equity","daily_start_equity","realized_pnl","unrealized_pnl"],
        "TradingAccount": ["cash_equity","equity","peak_equity","daily_start_equity","realized_pnl","unrealized_pnl","reserved_margin"],
        "Trade": ["quantity","requested_quantity","filled_quantity","remaining_quantity","requested_price","average_fill_price","fee","notional","stop_loss_price","take_profit_price"],
        "Position": ["quantity","average_entry_price","mark_price","realized_pnl","unrealized_pnl","reserved_capital"],
        "Withdrawal": ["amount"], "Wallet": ["available_balance","locked_balance"],
        "ReferralCommission": ["gross_revenue","commission_amount"],
        "RevenueLedger": ["gross_amount","refunds","net_amount"], "CostLedger": ["amount"],
        "SmartTrade": ["entry_price","quantity","stop_loss_price","take_profit_1","take_profit_2","take_profit_3"],
        "DcaBot": ["initial_quote","safety_order_quote"], "GridBot": ["lower_price","upper_price","quote_per_grid"],
        "TradeExecutor": ["executed_quantity","target_quantity"], "FundingTransaction": ["amount"],
    }
    assert 'class FinancialNumeric(TypeDecorator)' in source
    assert 'impl = Numeric(38, 18, asdecimal=False)' in source
    for cls, cols in targets.items():
        m = re.search(rf'^class {cls}\(Base\):', source, re.M)
        assert m, f"missing model {cls}"
        n = re.search(r'^class \w+\(Base\):', source[m.end():], re.M)
        block = source[m.start():m.end()+n.start()] if n else source[m.start():]
        for col in cols:
            assert re.search(rf'^    {re.escape(col)}: Mapped\[float\] = mapped_column\(FinancialNumeric', block, re.M), f"{cls}.{col} not FinancialNumeric"


def test_default_and_live_database_safety_contract():
    cfg = (ROOT / "app/config.py").read_text()
    main = (ROOT / "app/main.py").read_text()
    assert 'database_url: str = "sqlite+aiosqlite:///./data/trading.db"' in cfg
    assert 'PostgreSQL is required outside development' in main


def test_withdrawal_digest_uses_canonical_decimal_text():
    from app.withdrawal_security import canonical_proposal
    assert b'"amount":"1.23"' in canonical_proposal(request_id="x", amount=Decimal("1.2300"), currency="USDT", destination="T123")
    assert canonical_proposal(request_id="x", amount=0.0, currency="USDT", destination="T123") == canonical_proposal(request_id="x", amount=Decimal("-0"), currency="USDT", destination="T123")


def test_withdrawal_velocity_has_no_row_cap():
    source = (ROOT / "app/withdrawal_risk.py").read_text()
    assert '.limit(100)' not in source
    assert 'func.sum' in source


def test_usdt_tron_no_custom_keccak_tables_remain():
    source = (ROOT / "app/usdt_tron.py").read_text()
    assert '_ROT' not in source and '_RC' not in source
    req = (ROOT / "requirements.txt").read_text()
    assert 'bip-utils==2.12.2' in req
    assert 'pycryptodomex==3.23.0' not in req
    assert 'from bip_utils import Bip44' in source
    assert '_derive_path' not in source


def test_sensitive_plaintext_fails_closed_outside_development():
    crypto = (ROOT / "app/crypto.py").read_text()
    assert 'environment.lower() in {"production", "staging"}' in crypto
    assert 'Unencrypted sensitive database value detected outside development' in crypto
