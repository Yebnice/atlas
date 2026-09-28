from app.fx_execution_router import FXQuote, route_fx_quotes

NOW = 1_700_000_000_000


def q(provider, bid, ask, bid_size=1_000_000, ask_size=1_000_000, latency=10, fee=0.2, age=0):
    return FXQuote(provider, "EURUSD", bid, ask, bid_size, ask_size, NOW-age, 0.0, fee, latency)


def test_selects_lowest_executable_cost_provider():
    plan = route_fx_quotes(symbol="EURUSD", side="buy", quantity=100_000,
                           quotes=[q("lp-a", 1.0999, 1.1001, fee=0.8),
                                   q("lp-b", 1.09995, 1.10005, fee=0.2)], now_ms=NOW)
    assert plan.provider == "lp-b"
    assert plan.order_type == "RFQ"
    assert plan.execution_authority is False


def test_stale_quote_is_rejected():
    plan = route_fx_quotes(symbol="EURUSD", side="buy", quantity=100_000,
                           quotes=[q("lp-a", 1.0999, 1.1001, age=2_000)], now_ms=NOW)
    assert plan.provider is None
    assert plan.order_type == "NO_TRADE"


def test_insufficient_depth_is_rejected():
    plan = route_fx_quotes(symbol="EURUSD", side="buy", quantity=2_000_000,
                           quotes=[q("lp-a", 1.0999, 1.1001, ask_size=1_000_000)], now_ms=NOW)
    assert plan.provider is None
    assert not plan.sufficient_depth


def test_cost_budget_blocks_expensive_market():
    plan = route_fx_quotes(symbol="EURUSD", side="buy", quantity=100_000,
                           quotes=[q("lp-a", 1.0990, 1.1010, fee=5.0)], now_ms=NOW,
                           max_total_cost_bps=1.0)
    assert plan.order_type == "NO_TRADE"
    assert plan.provider is None


def test_symbol_mismatch_is_not_used():
    plan = route_fx_quotes(symbol="GBPUSD", side="buy", quantity=100_000,
                           quotes=[q("lp-a", 1.0999, 1.1001)], now_ms=NOW)
    assert plan.provider is None
