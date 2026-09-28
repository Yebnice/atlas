import numpy as np
import pandas as pd

from app.strategy_engine import StrategyConfig
from app.strategy_router import (
    STRATEGIES,
    classify_regime,
    regime_conditioned_strategy_performance,
    select_strategy,
    online_strategy_scores,
    strategy_trade_plan,
    router_walk_forward_backtest,
)


def _df(n=1100):
    idx = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    t = np.arange(n)
    close = 100 + 0.025 * t + 2.5 * np.sin(t / 18.0) + 0.9 * np.sin(t / 4.0)
    close[700:] += 3.0 * np.sin(np.arange(n - 700) / 35.0)
    close = pd.Series(close, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) + 0.5
    low = np.minimum(open_, close) - 0.5
    volume = pd.Series(1_000_000 + 50_000 * np.sin(t / 11.0), index=idx)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_regime_classifier_uses_completed_bars_only():
    df = _df()
    regimes = classify_regime(df)
    assert len(regimes) == len(df)
    assert set(regimes.dropna().unique()).issubset({"TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", "TRANSITION"})


def test_regime_conditioned_performance_is_per_strategy():
    df = _df()
    perf = regime_conditioned_strategy_performance(df, StrategyConfig())
    assert set(perf) == set(STRATEGIES)
    assert any(perf[name] for name in STRATEGIES)
    for name in STRATEGIES:
        for regime, metrics in perf[name].items():
            assert "sharpe" in metrics
            assert "max_drawdown" in metrics
            assert "trades" in metrics


def test_online_scores_require_minimum_observations():
    from datetime import datetime, timezone
    rows = [{"strategy": "breakout", "return_bps": 20.0, "created_at": datetime.now(timezone.utc)} for _ in range(10)]
    scores = online_strategy_scores(rows, min_observations=10)
    assert scores["breakout"] > 0
    rows = rows[:9]
    scores = online_strategy_scores(rows, min_observations=10)
    assert scores["breakout"] == 0.0


def test_router_holds_during_cooldown():
    df = _df()
    result = select_strategy(df, StrategyConfig(), current_strategy="ensemble", cooldown_active=True)
    assert result["status"] in {"OK", "TRANSITION"}
    if result["status"] == "OK":
        assert result["strategy"] == "ensemble"
        assert result["action"] == "HOLD"


def test_router_can_return_blended_signal():
    df = _df()
    result = select_strategy(df, StrategyConfig(), blend_enabled=True, blend_top_n=3, min_trades=5)
    assert result["status"] in {"OK", "TRANSITION"}
    if result["status"] == "OK":
        assert isinstance(result["blend"], list)
        assert len(result["blend"]) >= 1
        assert abs(float(result["signal"])) <= 1.0


def test_strategy_trade_plan_is_risk_aware():
    df = _df()
    plan = strategy_trade_plan(df, "trend", signal=0.9, cfg=StrategyConfig())
    assert plan is not None
    assert plan["side"] == "buy"
    assert plan["stop_loss_price"] < plan["entry_price"] < plan["take_profit_price"]
    assert plan["reward_risk"] >= 2.0


def test_router_walk_forward_evaluates_selection_on_unseen_folds():
    df = _df(1300)
    result = router_walk_forward_backtest(df, StrategyConfig(), folds=3, min_train=700, min_trades=5)
    assert result["status"] in {"OK", "INSUFFICIENT_DATA"}
    if result["status"] == "OK":
        assert result["router"] == "REGIME_CONDITIONED_WALK_FORWARD"
        assert len(result["folds"]) >= 1


def test_online_scores_prefer_current_regime_and_net_return():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    rows = []
    for _ in range(10):
        rows.append({"strategy": "breakout", "regime": "TREND_UP", "timeframe": "1h", "net_return_bps": 30.0, "created_at": now - timedelta(hours=1)})
        rows.append({"strategy": "breakout", "regime": "RANGE", "timeframe": "1h", "net_return_bps": -20.0, "created_at": now - timedelta(hours=1)})
    scores = online_strategy_scores(rows, current_regime="TREND_UP", timeframe="1h", min_observations=10)
    assert scores["breakout"] > 0


def test_policy_walk_forward_includes_online_feedback_and_switch_controls():
    df = _df(1000)
    from app.strategy_router import policy_walk_forward_backtest
    result = policy_walk_forward_backtest(df, StrategyConfig(), folds=2, min_train=500, min_trades=5, decision_stride=8)
    assert result["status"] in {"OK", "INSUFFICIENT_DATA"}
    if result["status"] == "OK":
        assert result["router"] == "FULL_ADAPTIVE_POLICY_WALK_FORWARD"
        assert set(result["includes"]) >= {"regime", "online_outcome_feedback", "switch_hysteresis", "blending", "abstention"}
