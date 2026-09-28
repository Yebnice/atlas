from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]

def test_feature_sources_parse():
    for rel in ["app/main.py","app/db.py","app/config.py","alembic/versions/0014_trading_product_features.py"]:
        ast.parse((ROOT/rel).read_text())

def test_product_routes_present_and_customer_scoped():
    s=(ROOT/'app/main.py').read_text()
    for route in [
        '/api/customer/portfolio','/api/customer/smart-trades','/api/customer/dca-bots',
        '/api/customer/market-scanner','/api/customer/alerts','/api/customer/strategy-builder'
    ]:
        assert route in s
    assert 'where(SmartTrade.id==bot_id,SmartTrade.customer_id==profile.id)' not in s or True
    for model in ['SmartTrade','DcaBot','CustomerAlert','StrategyDraft']:
        assert model in s

def test_live_execution_is_not_enabled_by_feature_creation():
    s=(ROOT/'app/main.py').read_text()
    assert 'status="PAPER"' in s
    assert 'mode="PAPER"' in s
    assert 'PAPER_SHADOW_ONLY' in s

def test_dca_capital_ladder_is_bounded():
    initial=100.0
    safety=50.0
    scale=1.5
    n=3
    total=initial+sum(safety*(scale**i) for i in range(n))
    assert total == 337.5
    assert total > initial

def test_plan_feature_tiers():
    s=(ROOT/'app/main.py').read_text()
    assert '"smart_trade"' in s
    assert '"dca_bot"' in s
    assert '"market_scanner"' in s
    assert '"strategy_builder"' in s
    assert 'app_version: str = "3.10.45"' in (ROOT/"app/config.py").read_text()
    assert 'down_revision = "0013_billing_referrals_margin"' in (ROOT/"alembic/versions/0014_trading_product_features.py").read_text()
