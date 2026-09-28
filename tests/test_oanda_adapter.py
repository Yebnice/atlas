from app.forex_oanda import OandaBroker, OandaConfig


def test_oanda_practice_url_and_live_refusal():
    import pytest
    assert OandaConfig("acct", "token", True).base_url == "https://api-fxpractice.oanda.com"
    with pytest.raises(Exception, match="practice/demo-only"):
        OandaConfig("acct", "token", False)


def test_oanda_market_order_payload(monkeypatch):
    broker = OandaBroker(OandaConfig("acct", "token", True))
    captured = {}
    def fake(method, path, **kwargs):
        captured.update(kwargs)
        return {
            "lastTransactionID": "2",
            "orderCreateTransaction": {"id": "1"},
            "orderFillTransaction": {"units": "1000", "price": "1.10000"},
        }
    monkeypatch.setattr(broker, "_request", fake)
    monkeypatch.setattr(broker, "market_info", lambda instrument: {"tradeUnitsPrecision": 0, "displayPrecision": 5, "minimumTradeSize": 1, "maximumOrderUnits": 1000000})
    out = broker.market_order("EUR_USD", "buy", 1000, "cid-1", 1.09, 1.12)
    order = captured["json"]["order"]
    assert order["units"] == "1000"
    assert order["clientExtensions"]["id"] == "cid-1"
    assert order["stopLossOnFill"]["price"].startswith("1.09")
    assert order["takeProfitOnFill"]["price"].startswith("1.12")
    assert out["status"] == "closed"
    broker.close()



def test_oanda_order_normalization(monkeypatch):
    from app.forex_oanda import OandaBroker, OandaConfig
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    b._request = lambda method, path, **kwargs: {"order": {"id":"42","state":"FILLED","clientExtensions":{"id":"cid-1"}}, "orderFillTransaction":{"units":"10","price":"1.2345"}}
    result = b.order("42")
    assert result["id"] == "42"
    assert result["status"] == "closed"
    assert result["filled"] == 10
    assert result["clientOrderId"] == "cid-1"


def test_oanda_quote_age_and_practice_stream_url():
    from datetime import datetime, timezone, timedelta
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    fresh = (datetime.now(timezone.utc) - timedelta(seconds=0.2)).isoformat().replace("+00:00", "Z")
    assert b.quote_age_seconds(fresh) < 2
    assert b.pricing_stream_url() == "https://stream-fxpractice.oanda.com/v3/accounts/acct/pricing/stream"


def test_oanda_practice_quote_validation(monkeypatch):
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    def fake(method, path, **kwargs):
        if path.endswith("/pricing"):
            return {"prices": [{"instrument": "EUR_USD", "tradeable": True, "time": ts,
                                 "bids": [{"price": "1.10000", "liquidity": 100000}],
                                 "asks": [{"price": "1.10002", "liquidity": 100000}]}]}
        return {"instruments": [{"name":"EUR_USD", "tradeUnitsPrecision":0, "minimumTradeSize":"1", "maximumOrderUnits":"1000000"}]}
    b._request = fake
    out = b.validate_practice_quote("EUR_USD", 3)
    assert out["tradeable"] is True
    assert out["ask"] == 1.10002
    assert out["spread"] > 0


def test_oanda_practice_quote_rejects_stale(monkeypatch):
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    from datetime import datetime, timezone, timedelta
    ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    b._request = lambda method, path, **kwargs: ({"prices": [{"instrument":"EUR_USD","tradeable":True,"time":ts,"bids":[{"price":"1.1"}],"asks":[{"price":"1.1001"}]}]} if path.endswith("/pricing") else {"instruments":[{"name":"EUR_USD"}]})
    import pytest
    with pytest.raises(Exception, match="stale"):
        b.validate_practice_quote("EUR_USD", 3)


def test_oanda_direct_client_order_lookup(monkeypatch):
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    calls = []
    def fake(method, path, **kwargs):
        calls.append(path)
        if path.endswith("/orders/@cid-7"):
            return {"order": {"id": "77"}}
        return {"order": {"id": "77", "state": "FILLED", "clientExtensions": {"id": "cid-7"}},
                "orderFillTransaction": {"units": "100", "price": "1.2"}}
    b._request = fake
    out = b.find_order_by_client_id("cid-7")
    assert out["id"] == "77"
    assert calls[0].endswith("/orders/@cid-7")


def test_oanda_transactions_since_and_stream_urls():
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    captured = {}
    b._request = lambda method, path, **kwargs: captured.update(path=path, params=kwargs.get("params")) or {"lastTransactionID":"9","transactions":[]}
    out = b.transactions_since("8")
    assert out["lastTransactionID"] == "9"
    assert captured["params"] == {"id":"8"}
    assert b.transaction_stream_url().endswith("/v3/accounts/acct/transactions/stream")


def test_oanda_stream_line_parser():
    from app.forex_oanda import OandaBroker
    assert OandaBroker.parse_stream_line('{"type":"HEARTBEAT","lastTransactionID":"10"}')["type"] == "HEARTBEAT"
    assert OandaBroker.parse_stream_line("not-json") is None


def test_oanda_account_changes_uses_cursor():
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    captured = {}
    b._request = lambda method, path, **kwargs: captured.update(path=path, params=kwargs.get("params")) or {
        "lastTransactionID": "12", "changes": {"ordersCreated": []}, "state": {}
    }
    out = b.account_changes("10")
    assert out["lastTransactionID"] == "12"
    assert captured["path"].endswith("/accounts/acct/changes")
    assert captured["params"] == {"sinceTransactionID": "10"}


def test_oanda_resolve_unknown_is_read_only(monkeypatch):
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    calls = []
    b.find_order_by_client_id = lambda cid: calls.append(("lookup", cid)) or {
        "id": "77", "status": "closed", "filled": 100, "average": 1.2, "price": 1.2, "clientOrderId": cid
    }
    def fail(*args, **kwargs):
        raise AssertionError("resolve_unknown_order must not resubmit an order")
    b.market_order = fail
    out = b.resolve_unknown_order("cid-timeout", "8")
    assert out["id"] == "77"
    assert calls == [("lookup", "cid-timeout")]


def test_oanda_resolve_unknown_uses_transaction_fallback():
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    b.find_order_by_client_id = lambda cid: None
    b.transactions_since = lambda tx: {"transactions": [{"id": "90", "orderID": "77",
        "clientExtensions": {"id": "cid-late"}}], "lastTransactionID": "90"}
    b.order = lambda oid: {"id": oid, "status": "closed", "filled": 100, "average": 1.2, "price": 1.2, "clientOrderId": "cid-late"}
    out = b.resolve_unknown_order("cid-late", "89")
    assert out["id"] == "77"
    assert out["status"] == "closed"


def test_oanda_resolve_unknown_without_cursor_does_not_guess():
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    b.find_order_by_client_id = lambda cid: None
    out = b.resolve_unknown_order("cid-missing")
    assert out is None
