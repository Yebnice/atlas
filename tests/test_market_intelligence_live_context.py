import asyncio
import pandas as pd


def test_trend_snapshot_and_risk_scoring():
    from app.market_intelligence import _trend_snapshot, _headline_risk
    idx = pd.date_range("2025-01-01", periods=100, freq="D", tz="UTC")
    close = [100 + i * 0.5 for i in range(100)]
    df = pd.DataFrame({"open": close, "high": [x+1 for x in close], "low": [x-1 for x in close], "close": close}, index=idx)
    snap = _trend_snapshot(df)
    assert snap["status"] == "OK"
    assert snap["trend"] == "UP"
    risk = _headline_risk([{"title": "Fed remains hawkish as inflation persists", "summary": "higher for longer"}])
    assert risk["risk_score"] > 0
    assert any(x[0] == "hawkish" for x in risk["risk_themes"])


def test_public_feed_failure_isolated(monkeypatch):
    import app.market_intelligence as mi
    class Bad:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("network down")
    monkeypatch.setattr(mi.httpx, "get", Bad())
    articles, failures = mi.fetch_public_news_sources(timeout=0.1)
    assert articles == []
    assert failures


def test_intelligence_is_research_only(monkeypatch):
    import app.market_intelligence as mi
    idx = pd.date_range("2025-01-01", periods=80, freq="D", tz="UTC")
    close = [100 + i * 0.2 for i in range(80)]
    df = pd.DataFrame({"open": close, "high": [x+1 for x in close], "low": [x-1 for x in close], "close": close}, index=idx)
    monkeypatch.setattr(mi, "yahoo_history", lambda *a, **k: df)
    monkeypatch.setattr(mi, "alpha_vantage_news", lambda *a, **k: [])
    monkeypatch.setattr(mi, "fetch_public_news_sources", lambda *a, **k: ([], {}))
    out = asyncio.run(mi.gather_market_intelligence(["BTC-USD"], "1y", ""))
    assert out["execution_authority"] is False
    assert out["trend_snapshots"]["BTC-USD"]["trend"] == "UP"


def test_derivatives_stress_is_risk_only_and_missing_data_lowers_confidence():
    from app.derivatives_risk import DerivativesSnapshot, derivatives_stress
    normal = derivatives_stress(DerivativesSnapshot(symbol="BTCUSDT", funding_rate=0.00001))
    assert normal["directional_signal"] is False
    assert normal["execution_authority"] is False
    assert normal["confidence"] < 1.0

    severe = derivatives_stress(DerivativesSnapshot(
        symbol="BTCUSDT", funding_rate=0.003, open_interest_change_pct=25,
        basis_pct=4, liquidation_notional=1.0, order_flow_imbalance=1.0,
    ))
    assert severe["state"] == "SEVERE"
    assert severe["action"] == "BLOCK_NEW_RISK"


def test_derivatives_normalizers_are_safe():
    from app.derivatives_risk import normalize_open_interest_change, basis_pct
    assert round(normalize_open_interest_change(100, 110), 4) == 10.0
    assert normalize_open_interest_change(0, 110) is None
    assert round(basis_pct(100, 101), 4) == 1.0
    assert basis_pct(0, 101) is None
