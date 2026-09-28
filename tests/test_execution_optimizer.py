import pytest
from app.execution_optimizer import BookLevel, build_execution_plan, executable_vwap


def test_vwap_walks_multiple_levels():
    vwap, remaining = executable_vwap([BookLevel(100, 2), BookLevel(101, 3)], 4)
    assert remaining == 0
    assert round(vwap, 6) == 100.5


def test_insufficient_depth_blocks_trade():
    plan = build_execution_plan(
        side="buy", quantity=10, best_price=100,
        levels=[BookLevel(100, 2)], maker_fee_bps=1, taker_fee_bps=5
    )
    assert plan.order_type == "NO_TRADE"
    assert plan.slices == 0


def test_high_urgency_prefers_market_when_cost_is_bounded():
    plan = build_execution_plan(
        side="buy", quantity=1, best_price=100,
        levels=[BookLevel(100, 1)], maker_fee_bps=1, taker_fee_bps=5,
        urgency=1.0, max_adverse_bps=20
    )
    assert plan.order_type == "MARKET"


def test_low_urgency_can_choose_maker_when_modelled_cost_is_lower():
    plan = build_execution_plan(
        side="buy", quantity=1, best_price=100,
        levels=[BookLevel(100, 1)], maker_fee_bps=0.5, taker_fee_bps=10,
        urgency=0.1, max_adverse_bps=50
    )
    assert plan.order_type == "LIMIT_MAKER"


def test_negative_fee_is_rejected():
    with pytest.raises(ValueError):
        build_execution_plan(side="buy", quantity=1, best_price=100,
                             levels=[BookLevel(100, 1)], maker_fee_bps=-1, taker_fee_bps=5)
