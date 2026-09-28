from app.risk_governor import evaluate_trade

def test_live_requires_stop():
    d=evaluate_trade(side="buy",price=100,quantity=1,live=True,stop_loss_price=None,take_profit_price=None,signal={})
    assert d.action=="BLOCK" and "live_protective_stop_missing" in d.reasons

def test_paper_valid_trade_allowed():
    d=evaluate_trade(side="buy",price=100,quantity=1,live=False,stop_loss_price=95,take_profit_price=110,signal={})
    assert d.action=="ALLOW"

def test_spread_guard():
    d=evaluate_trade(side="buy",price=100,quantity=1,live=True,stop_loss_price=95,take_profit_price=110,signal={},spread_bps=150,max_spread_bps=100)
    assert d.action=="BLOCK"


def test_risk_per_trade_limit_blocks_oversized_stop_risk():
    d=evaluate_trade(side="buy",price=100,quantity=10,live=True,stop_loss_price=90,take_profit_price=120,signal={},equity=1000,risk_per_trade=0.005)
    assert d.action=="BLOCK" and "risk_per_trade_limit" in d.reasons

def test_risk_per_trade_limit_allows_sized_position():
    d=evaluate_trade(side="buy",price=100,quantity=0.5,live=True,stop_loss_price=90,take_profit_price=120,signal={},equity=1000,risk_per_trade=0.005,risk_tolerance=0.10)
    assert d.action=="ALLOW"
