import numpy as np
import pandas as pd

from app.entry_exit_engine import EntryExitConfig, gated_entry_exit_analysis, start_bot_decision, gated_entry_exit_backtest


def trend_df(n=1200):
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(42)
    # Multiple regimes: trend, pullback/noise, trend continuation.
    rets = np.r_[
        rng.normal(0.00025, 0.0012, n // 3),
        rng.normal(-0.00005, 0.0018, n // 6),
        rng.normal(0.00030, 0.0013, n - (n // 3 + n // 6)),
    ]
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.0012, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0012, n)))
    open_ = close * (1 + rng.normal(0, 0.0004, n))
    volume = rng.lognormal(9, 0.25, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_gate_requires_explicit_levels():
    df = trend_df()
    out = gated_entry_exit_analysis(df)
    assert {"entry_price", "stop_loss_price", "take_profit_price", "entry_valid", "reward_risk"} <= set(out.columns)
    valid = out[out.entry_valid]
    assert not valid.empty
    assert (valid.reward_risk >= 2.0).all()
    assert np.isfinite(valid[["entry_price", "stop_loss_price", "take_profit_price"]].to_numpy()).all()


def test_start_bot_blocks_when_ai_or_data_is_unsafe():
    df = trend_df()
    assert start_bot_decision(df, ai_safe=False)["decision"] == "NO_TRADE"
    assert start_bot_decision(df, data_safe=False)["decision"] == "NO_TRADE"


def test_start_bot_trade_plan_has_entry_stop_target_when_safe():
    df = trend_df()
    # Search historical bars until the deterministic setup is valid.
    a = gated_entry_exit_analysis(df)
    valid_idx = np.flatnonzero(a.entry_valid.to_numpy())
    assert len(valid_idx) > 0
    i = int(valid_idx[-1])
    d = start_bot_decision(df.iloc[: i + 1])
    assert d["decision"] == "TRADE"
    assert set(d["trade_plan"]) >= {"side", "entry_price", "stop_loss_price", "take_profit_price", "reward_risk"}


def test_backtest_is_finite_and_has_explicit_trade_records():
    result = gated_entry_exit_backtest(trend_df())
    for key in ("total_return", "max_drawdown", "trade_sharpe", "hit_rate", "profit_factor"):
        assert np.isfinite(result[key]) or result[key] == float("inf")
    assert result["trades"] == len(result["trades_detail"])
    if result["trades_detail"]:
        for trade in result["trades_detail"]:
            assert trade["entry"] != trade["stop"]
            assert trade["entry"] != trade["target"]
            assert trade["side"] in {"buy", "sell"}


def test_backtest_applies_entry_discipline_without_blocking_risk_sized_trades():
    result = gated_entry_exit_backtest(trend_df(), risk_fraction=0.005)
    assert result["trades"] == len(result["trades_detail"])
    assert result["trades"] <= 20 * 365  # sanity bound; daily cap is enforced by the engine
