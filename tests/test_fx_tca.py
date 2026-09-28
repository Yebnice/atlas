from app.fx_tca import FXExecutionObservation, evaluate_fx_execution


def test_buy_tca_measures_cost_and_adverse_selection():
    r = evaluate_fx_execution(FXExecutionObservation(
        provider="lp-a", symbol="EURUSD", side="buy", quantity=1_000_000,
        arrival_mid=1.1000, execution_price=1.10011, executed_quantity=1_000_000,
        arrival_timestamp_ms=1000, execution_timestamp_ms=1050, fee_bps=0.2,
        mid_after_1s=1.09999, mid_after_5s=1.09990,
    ))
    assert r.implementation_shortfall_bps > 0
    assert r.net_execution_cost_bps > r.implementation_shortfall_bps
    assert r.adverse_selection_1s_bps < 0
    assert r.quality in {"GOOD", "ACCEPTABLE"}


def test_partial_fill_is_flagged():
    r = evaluate_fx_execution(FXExecutionObservation(
        provider="lp-a", symbol="USDJPY", side="sell", quantity=1_000_000,
        arrival_mid=150.0, execution_price=149.99, executed_quantity=500_000,
        arrival_timestamp_ms=1000, execution_timestamp_ms=1100,
    ))
    assert r.fill_ratio == 0.5
    assert r.quality == "PARTIAL"


def test_invalid_prices_are_rejected():
    import pytest
    with pytest.raises(ValueError):
        evaluate_fx_execution(FXExecutionObservation(
            provider="lp-a", symbol="EURUSD", side="buy", quantity=1,
            arrival_mid=0, execution_price=1.1, executed_quantity=1,
            arrival_timestamp_ms=1, execution_timestamp_ms=2,
        ))
