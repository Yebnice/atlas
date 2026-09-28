import pytest
from app.binance_subaccounts import BinanceSubAccountError, build_provision_plan, validate_provision_response


def test_plan_is_least_privilege():
    p = build_provision_plan(42, "atlas-c42")
    assert p["create_api_key"] == {"canTrade": True, "marginTrade": False, "futuresTrade": False, "enableWithdrawals": False, "universalTransfer": False}
    assert p["required_permissions"]["universalTransfer"] is False
    assert p["required_permissions"]["enableWithdrawals"] is False
    assert p["database_secret_storage"] is False


def test_response_requires_trade_and_rejects_transfer():
    out = validate_provision_response(42, "atlas-c42", {"subaccountId": "sub-1", "apiKey": "k", "secretKey": "s", "canTrade": True, "enableWithdrawals": False})
    assert out.trading_only is True
    assert out.secret_key == "s"
    with pytest.raises(BinanceSubAccountError):
        validate_provision_response(42, "atlas-c42", {"subaccountId": "sub-1", "canTrade": True, "canUniversalTransfer": True, "enableWithdrawals": False})
    with pytest.raises(BinanceSubAccountError):
        validate_provision_response(42, "atlas-c42", {"subaccountId": "sub-1", "canTrade": True, "enableWithdrawals": True})


def test_response_requires_subaccount():
    with pytest.raises(BinanceSubAccountError):
        validate_provision_response(42, "atlas-c42", {"canTrade": True})
