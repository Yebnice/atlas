import asyncio
import pandas as pd


def test_yahoo_normalization():
    from app.market_intelligence import _normalize_ohlcv
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    df = pd.DataFrame({"Open": [1,2,3], "High": [2,3,4], "Low": [0.5,1.5,2.5], "Close": [1.5,2.5,3.5], "Volume": [10,20,30]}, index=idx)
    out = _normalize_ohlcv(df)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out.iloc[-1]["close"] == 3.5


def test_news_summary():
    from app.market_intelligence import summarize_news
    out = summarize_news([
        {"overall_sentiment_score": 0.2, "topics": [{"topic": "earnings"}]},
        {"overall_sentiment_score": -0.1, "topics": [{"topic": "earnings"}, {"topic": "economy"}]},
    ])
    assert out["article_count"] == 2
    assert abs(out["average_sentiment"] - 0.05) < 1e-9
    assert out["top_topics"][0] == ("earnings", 2)


def test_daily_run_does_not_trade(monkeypatch):
    import app.daily_research as dr
    class FakeDF:
        pass
    async def fake_lock(*args, **kwargs): return True
    async def fake_release(*args, **kwargs): return None
    async def fake_intel(*args, **kwargs):
        return {"histories": {}, "failures": {}, "news": [], "news_summary": {}, "news_error": ""}
    monkeypatch.setattr(dr, "acquire_lock", fake_lock)
    monkeypatch.setattr(dr, "release_lock", fake_release)
    monkeypatch.setattr(dr, "gather_market_intelligence", fake_intel)
    out = asyncio.run(dr.run_daily_research())
    assert out["status"] == "NO_DATA"
    assert out["real_money_execution"] is False
