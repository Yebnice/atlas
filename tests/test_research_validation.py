import numpy as np
import pandas as pd

from app.research_validation import (
    validate_ohlcv_frame, purged_walk_forward_splits, bootstrap_mean_ci,
    multiple_testing_sharpe_adjustment, cost_sensitivity, ohlc_trade_ambiguity,
    fixed_signal_walk_forward_oos, regime_conditioned_performance,
)


def frame(n=100):
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    c = pd.Series(np.linspace(100, 110, n), index=idx)
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 100}, index=idx)


def test_validate_ohlcv_and_splits():
    df = frame()
    assert validate_ohlcv_frame(df)["valid"]
    folds = purged_walk_forward_splits(200, folds=4, min_train=80, purge=2, embargo=3)
    assert folds and all(f.test_start > f.train_end for f in folds)
    assert all(f.purge == 2 and f.embargo == 3 for f in folds)


def test_validation_statistics_are_deterministic():
    ci = bootstrap_mean_ci(np.full(50, 0.001), samples=200, seed=9, block_size=5)
    assert ci["status"] == "OK" and ci["ci_low"] > 0
    adj = multiple_testing_sharpe_adjustment([0.2, 0.4, 0.8], 3)
    assert adj["status"] == "OK"
    costs = cost_sensitivity(np.full(20, 0.001), np.full(20, 0.1), [5, 50])
    assert costs[0]["total_return"] > costs[1]["total_return"]


def test_ohlc_ambiguity_is_detected():
    df = frame(2)
    stop = pd.Series([99, 109], index=df.index)
    target = pd.Series([101, 111], index=df.index)
    side = pd.Series(["buy", "buy"], index=df.index)
    out = ohlc_trade_ambiguity(df, stop, target, side)
    assert out["ambiguous"] == 2
    assert out["policy"] == "WORST_CASE"


def test_oos_and_regime_metrics_are_forward_only_and_finite():
    df = frame(1000)
    signal = pd.Series(0.5, index=df.index)
    out = fixed_signal_walk_forward_oos(df, signal, costs_bps=7.5, folds=3, min_train=500)
    assert out["status"] == "OK" and out["oos_bars"] > 0
    regimes = regime_conditioned_performance(df, pd.Series(0.001, index=df.index))
    assert regimes and all(np.isfinite(v["total_return"]) for v in regimes.values())
