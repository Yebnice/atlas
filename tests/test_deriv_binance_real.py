import pytest
from app.deriv import DerivBroker, DerivConfig, DerivError
from app.binance_arbitrage_live import BinanceArbitrageBroker, BinanceArbConfig, BinanceArbitrageError


def test_deriv_live_disabled_by_default():
    b = DerivBroker(DerivConfig(1, "token", live=False))
    with pytest.raises(DerivError):
        import asyncio
        asyncio.run(b.buy("p", 1))


def test_deriv_config_requires_token():
    with pytest.raises(DerivError):
        DerivBroker(DerivConfig(1, ""))


def test_binance_live_disabled_by_default():
    b = BinanceArbitrageBroker(BinanceArbConfig("k", "s", live_enabled=False))
    with pytest.raises(BinanceArbitrageError):
        b.execute_ioc_leg("BTC/USDT", "BUY", 0.001, 100000)


def test_binance_config_has_sandbox_default():
    c = BinanceArbConfig("k", "s")
    assert c.sandbox is True
    assert c.live_enabled is False


def test_binance_recovery_blocks_partial_leg():
    from app.binance_arb_reconcile import BinanceArbRecovery
    receipt = {"status": "open", "filled": 0.4}
    assert BinanceArbRecovery.can_continue(receipt, 1.0) is False
    assert BinanceArbRecovery.exposure_after_partial(receipt, "BUY", 1.0)["unhedged_quantity"] == 0.4


def test_binance_filter_validation_rejects_bad_lot():
    from app.binance_arb_reconcile import validate_symbol_filters, BinanceArbRecoveryError
    info = {"filters": [{"filterType":"LOT_SIZE","minQty":"0.01","maxQty":"10","stepSize":"0.01"}, {"filterType":"MIN_NOTIONAL","minNotional":"10"}]}
    with pytest.raises(BinanceArbRecoveryError):
        validate_symbol_filters(info, "BUY", 0.005, 2000, 10)


def test_binance_filter_validation_accepts_valid_order():
    from app.binance_arb_reconcile import validate_symbol_filters
    info = {"filters": [{"filterType":"PRICE_FILTER","minPrice":"0.01","maxPrice":"1000000","tickSize":"0.01"}, {"filterType":"LOT_SIZE","minQty":"0.01","maxQty":"10","stepSize":"0.01"}, {"filterType":"MIN_NOTIONAL","minNotional":"10"}]}
    validate_symbol_filters(info, "BUY", 0.01, 2000.00, 20.0)
