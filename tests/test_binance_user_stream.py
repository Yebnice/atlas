import pytest
from app.binance_user_stream import parse_order_update, build_signed_subscription, BinanceUserStreamError
from app.binance_arb_reconcile import Exposure, neutralization_side, partial_leg_exposure


def test_parse_spot_execution_report():
    event = {"e":"executionReport","E":1000,"s":"BTCUSDT","i":123,"c":"atlas-1","X":"PARTIALLY_FILLED","x":"TRADE","S":"BUY","q":"1","z":"0.4","l":"0.4","L":"100","Z":"40"}
    r = parse_order_update(event)
    assert r.symbol == "BTCUSDT"
    assert r.executed_qty == 0.4
    assert r.terminal is False


def test_parse_wrapped_order_update():
    event = {"data":{"e":"executionReport","E":1001,"s":"ETHUSDT","i":456,"c":"atlas-2","X":"FILLED","x":"TRADE","S":"SELL","q":"2","z":"2","l":"2","L":"2000","Z":"4000"}}
    r = parse_order_update(event)
    assert r.terminal is True
    assert r.side == "SELL"


def test_parse_ignores_non_order_event():
    assert parse_order_update({"e":"outboundAccountPosition"}) is None


def test_parse_rejects_missing_identity():
    with pytest.raises(BinanceUserStreamError):
        parse_order_update({"e":"executionReport","s":"BTCUSDT","X":"NEW"})


def test_signed_subscription_shape():
    p = build_signed_subscription("key", 123, "sig")
    assert p["method"] == "userDataStream.subscribe.signature"
    assert p["params"]["apiKey"] == "key"


def test_partial_buy_creates_positive_base_exposure():
    e = partial_leg_exposure({"filled":0.4}, "BUY", "BTC", 1.0)
    assert e.asset == "BTC" and e.quantity == 0.4
    assert neutralization_side(e) == "SELL"


def test_partial_sell_creates_negative_base_exposure():
    e = partial_leg_exposure({"filled":0.4}, "SELL", "ETH", 1.0)
    assert e.quantity == -0.4
    assert neutralization_side(e) == "BUY"
