from pathlib import Path

from app.forex_oanda import OandaBroker, OandaConfig


def test_oanda_price_and_units_are_normalized_to_account_instrument_rules(monkeypatch):
    broker = OandaBroker(OandaConfig("acct", "token", True))
    monkeypatch.setattr(broker, "market_info", lambda instrument: {
        "tradeUnitsPrecision": 0,
        "displayPrecision": 3,
        "minimumTradeSize": 1,
        "maximumOrderUnits": 10000,
    })
    assert broker.validate_order_units("XAU_USD", 12.7) == 13
    assert broker.normalize_price("XAU_USD", 123.45678) == 123.457


def test_oanda_is_demo_only_and_live_customer_path_is_blocked():
    execution = Path("app/execution.py").read_text(encoding="utf-8")
    customer = Path("app/customer_oanda.py").read_text(encoding="utf-8")
    main = Path("app/main.py").read_text(encoding="utf-8")
    assert "forex_live = False" in execution
    assert "OANDA is demo/backtesting-only in AtlasRisk" in execution
    assert "OANDA live execution is disabled" in execution
    assert 'if not bool(getattr(account, "practice", True))' in customer
    assert "if settings.forex_live_enabled:" in main
    assert "live OANDA accounts are not supported" in main


def test_major_asset_universe_and_customer_connection_exist():
    cfg = Path("app/config.py").read_text(encoding="utf-8")
    main = Path("app/main.py").read_text(encoding="utf-8")
    assert "EUR_USD,GBP_USD,USD_JPY,USD_CHF,AUD_USD,USD_CAD,NZD_USD" in cfg
    assert "XAU_USD,XAG_USD,WTICO_USD,BCO_USD,NATGAS_USD" in cfg
    assert "/api/customer/broker/oanda/connect" in main
    assert "CustomerOandaAccount" in main


def test_customer_ui_exposes_fx_and_commodity_markets():
    html = Path("app/templates/customer.html").read_text(encoding="utf-8")
    assert 'value="forex">Major FX' in html
    assert 'value="commodity">Commodities' in html
    assert "XAU_USD" in html
    assert "EUR_USD" in html
