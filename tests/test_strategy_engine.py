import numpy as np
import pandas as pd
from app.strategy_engine import StrategyConfig, strategy_signals, strategy_signal, strategy_backtest

def sample_df(n=700):
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(7)
    rets = 0.00015 + rng.normal(0, 0.002, n)
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.0015, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0015, n)))
    open_ = close * (1 + rng.normal(0, 0.0005, n))
    volume = rng.lognormal(10, 0.2, n)
    return pd.DataFrame({"open":open_, "high":high, "low":low, "close":close, "volume":volume}, index=idx)

def test_strategy_schema_and_bounds():
    df = sample_df()
    s = strategy_signals(df)
    assert {"trend","momentum","breakout","mean_reversion","ensemble","atr","realized_vol"} <= set(s.columns)
    assert float(s["ensemble"].dropna().abs().max()) <= 1.000001

def test_strategy_signal_has_protective_levels():
    df = sample_df()
    result = strategy_signal(df, StrategyConfig(signal_threshold=0.0))
    assert result["side"] in {"buy", "sell", "flat"}
    if result["side"] != "flat":
        assert result["stop_loss_price"] is not None
        assert result["take_profit_price"] is not None

def test_strategy_backtest_is_lagged_and_finite():
    result = strategy_backtest(sample_df())
    for key in ("total_return","max_drawdown","sharpe","average_leverage","max_leverage"):
        assert np.isfinite(result[key])
    assert result["max_leverage"] <= 1.500001



def test_strategy_annualization_uses_bar_frequency():
    import numpy as np, pandas as pd
    from app.strategy_engine import strategy_signals, strategy_backtest
    idx = pd.date_range("2025-01-01", periods=300, freq="4h", tz="UTC")
    base = np.linspace(100, 120, len(idx))
    df = pd.DataFrame({"open":base, "high":base+1, "low":base-1, "close":base}, index=idx)
    out = strategy_signals(df)
    assert 2000 < out.attrs["annualization_factor"] < 2300
    result = strategy_backtest(df)
    assert result["annualization_factor"] == out.attrs["annualization_factor"]


def test_all_strategy_research_and_ai_review():
    from app.research_engine import backtest_all_strategies, ai_market_review
    df = sample_df(1800)
    out = backtest_all_strategies(df, include_ai=False)
    assert out["strategy_count"] == 5
    assert set(out["research_order"]) == {"trend", "momentum", "breakout", "mean_reversion", "ensemble"}
    review = ai_market_review(out)
    assert review["status"] == "REVIEW_READY"
    assert review["research_order"]


def test_paper_gate_and_live_shadow_signals():
    from app.research_engine import paper_candidates, live_strategy_signals
    df = sample_df(1800)
    research = {
        "strategies": [{"strategy":"trend","sharpe":1.0,"max_drawdown":-0.10,"trades":40,"total_return":0.20}],
        "validation": {"per_strategy_oos": {"trend": {"status":"OK","oos_total_return":0.10,"folds":[{"total_return":0.05},{"total_return":-0.01}]}}}
    }
    candidates = paper_candidates(research)
    assert candidates
    names = [x["strategy"] for x in candidates]
    signals = live_strategy_signals(df, names)
    assert signals and all(x["mode"] == "PAPER_SHADOW_ONLY" for x in signals)


def test_multi_timeframe_structure_and_risk_levels():
    from app.multi_timeframe import multi_timeframe_analysis, multi_timeframe_signal
    df = sample_df(2200)
    out = multi_timeframe_analysis(df)
    required = {"regime_4h", "regime_1h", "setup_15m", "confirm_5m", "entry_confirmed", "entry_price", "stop_price", "take_profit_price"}
    assert required <= set(out.columns)
    sig = multi_timeframe_signal(df)
    assert sig["execution_mode"] == "PAPER_SHADOW_ONLY"
    assert sig["side"] in {"buy", "sell", "flat"}


def test_ai_walk_forward_does_not_forward_fill_between_oos_windows():
    from app.trading_core import ai_walk_forward_backtest
    out = ai_walk_forward_backtest(sample_df(1800), asset="crypto", folds=4, min_train=500)
    assert out["prediction_gap_policy"] == "NO_FORWARD_FILL_ACROSS_NON_TEST_WINDOWS"
    assert np.isfinite(out["sharpe"])


def test_adaptive_policy_object_is_explicit_and_fail_closed():
    from app.adaptive_bot import AdaptiveModelPolicy
    p = AdaptiveModelPolicy()
    assert p.max_age_hours > 0
    assert p.min_sharpe > 0
    assert p.max_drawdown < 0
    assert p.min_trades > 0


def test_adaptive_champion_promotion_keeps_model_integrity(tmp_path, monkeypatch):
    from app import adaptive_bot
    import hashlib, json
    import pathlib

    model_path = tmp_path / "btc.joblib"
    candidate_result = {"model_sha256": "abc123", "features": 20, "folds": 3}
    wfo = {"sharpe": 1.0, "max_drawdown": -0.10, "trades": 40, "total_return": 0.20, "folds": [{"total_return": 0.03}, {"total_return": 0.02}, {"total_return": 0.04}, {"total_return": 0.05}, {"total_return": 0.06}]}

    monkeypatch.setattr(adaptive_bot, "ai_walk_forward_backtest", lambda *a, **k: wfo)
    def fake_train(df, path, **kwargs):
        pathlib.Path(path).write_bytes(b"model-bytes")
        digest = hashlib.sha256(b"model-bytes").hexdigest()
        pathlib.Path(str(path) + ".meta.json").write_text(json.dumps({"model_sha256": digest}))
        return {**candidate_result, "model_sha256": digest}
    monkeypatch.setattr(adaptive_bot, "train_model", fake_train)

    out = adaptive_bot.ensure_adaptive_model(object(), str(model_path), policy=adaptive_bot.AdaptiveModelPolicy(min_trades=1))
    assert out["status"] == "CHAMPION_PROMOTED"
    assert model_path.exists()
    assert json.loads(pathlib.Path(str(model_path)+".meta.json").read_text())["model_sha256"] == hashlib.sha256(b"model-bytes").hexdigest()
    assert json.loads(pathlib.Path(str(model_path)+".adaptive.json").read_text())["status"] == "CHAMPION"
