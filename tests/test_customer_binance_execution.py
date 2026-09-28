from types import SimpleNamespace
import pytest

from app.customer_binance_execution import (
    CustomerBinanceExecutionError,
    build_customer_binance_broker,
    resolve_secret,
)


def account(**overrides):
    base = dict(status="VERIFIED", can_trade=True, universal_transfer=False, enable_withdrawals=False,
                api_key="customer-key", secret_ref="projects/p/secrets/c1/versions/1",
                market_type="spot")
    base.update(overrides)
    return SimpleNamespace(**base)


def test_secret_manager_reference_is_required():
    with pytest.raises(CustomerBinanceExecutionError):
        resolve_secret("")


def test_secret_fetcher_is_used_and_not_platform_fallback():
    seen = []
    secret = resolve_secret("ref", lambda ref: seen.append(ref) or "customer-secret")
    assert secret == "customer-secret"
    assert seen == ["ref"]


def test_verified_customer_binance_broker_uses_customer_credentials(monkeypatch):
    captured = {}
    class FakeBroker:
        pass
    def fake_get(config):
        captured.update(vars(config))
        return FakeBroker()
    import app.customer_binance_execution as mod
    monkeypatch.setattr(mod.Broker, "get", fake_get)
    broker = build_customer_binance_broker(account(), secret_fetcher=lambda _: "secret")
    assert isinstance(broker, FakeBroker)
    assert captured["exchange_id"] == "binance"
    assert captured["api_key"] == "customer-key"
    assert captured["api_secret"] == "secret"
    assert captured["market_type"] == "spot"
    assert captured["sandbox"] is False


@pytest.mark.parametrize("changes", [
    {"status": "PENDING"},
    {"status": "DISABLED"},
    {"can_trade": False},
    {"universal_transfer": True},
    {"enable_withdrawals": True},
    {"api_key": ""},
    {"secret_ref": ""},
])
def test_unverified_or_overprivileged_customer_mapping_is_rejected(changes):
    with pytest.raises(CustomerBinanceExecutionError):
        build_customer_binance_broker(account(**changes), secret_fetcher=lambda _: "secret")
