from app.forex_oanda import OandaBroker, OandaConfig, OandaUnknown


def test_timeout_is_unknown_not_retry(monkeypatch):
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    called = {"market": 0}
    def request(*args, **kwargs):
        raise OandaUnknown("timeout")
    b._request = request
    try:
        b.market_order("EUR_USD", "buy", 100, "cid-1")
    except OandaUnknown:
        pass
    else:
        raise AssertionError("timeout must remain UNKNOWN")
    assert called["market"] == 0


def test_duplicate_submission_path_is_forbidden():
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    b.find_order_by_client_id = lambda cid: {"id":"10", "status":"closed", "filled":100, "average":1.1, "price":1.1, "clientOrderId":cid}
    def forbidden(*args, **kwargs):
        raise AssertionError("must resolve existing order, not submit again")
    b.market_order = forbidden
    result = b.resolve_unknown_order("cid-duplicate")
    assert result["id"] == "10"


def test_malformed_stream_data_is_ignored():
    assert OandaBroker.parse_stream_line("not-json") is None
    assert OandaBroker.parse_stream_line("[]") is None
    assert OandaBroker.parse_stream_line("") is None


def test_quote_timestamp_missing_fails_closed():
    b = OandaBroker.__new__(OandaBroker)
    b.config = OandaConfig("acct", "token", True)
    b._request = lambda method, path, **kwargs: {"prices":[{"instrument":"EUR_USD","tradeable":True,"bids":[{"price":"1.1"}],"asks":[{"price":"1.1001"}]}]} if path.endswith("/pricing") else {"instruments":[{"name":"EUR_USD"}]}
    try:
        b.validate_practice_quote("EUR_USD", 3)
    except Exception as exc:
        assert "stale" in str(exc).lower() or "timestamp" in str(exc).lower()
    else:
        raise AssertionError("missing quote timestamp must fail closed")
