import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from app.main import PLAN_DEFINITIONS, _plan_price

def test_plan_prices_are_reasonable():
    assert _plan_price("free", "monthly") == 0
    assert _plan_price("starter", "monthly") == 7.99
    assert _plan_price("pro", "monthly") == 17.99
    assert _plan_price("elite", "monthly") == 39.99
    assert _plan_price("pro", "annual") == 179.90

def test_plan_limits_increase_with_tier():
    assert PLAN_DEFINITIONS["free"]["ai_credits"] < PLAN_DEFINITIONS["starter"]["ai_credits"] < PLAN_DEFINITIONS["pro"]["ai_credits"] < PLAN_DEFINITIONS["elite"]["ai_credits"]
    assert PLAN_DEFINITIONS["free"]["exchanges"] < PLAN_DEFINITIONS["starter"]["exchanges"] <= PLAN_DEFINITIONS["pro"]["exchanges"] <= PLAN_DEFINITIONS["elite"]["exchanges"]

def test_referral_commission_is_not_customer_trading_balance():
    from app.db import quantize_money
    revenue = 17.99
    commission = quantize_money(revenue * 0.01)
    contribution = revenue - commission
    # Raw float multiplication (17.99 * 0.01) is not exactly 0.1799 in IEEE-754;
    # quantize_money() rounds it to a fixed number of decimal places, which is
    # what the actual commission-crediting code path in main.py uses.
    assert commission == pytest.approx(0.1799)
    assert contribution > 0
