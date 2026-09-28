import numpy as np
import pandas as pd

from types import SimpleNamespace
from app.strategy_engine import StrategyConfig
from app.trade_learning import replay_trade_episode


def _df(n=700):
    idx = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
    t = np.arange(n)
    close = 100 + 0.03 * t + 2.0 * np.sin(t / 14.0)
    open_ = close.shift(0) if isinstance(close, pd.Series) else close
    close = pd.Series(close, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) + 0.6
    low = np.minimum(open_, close) - 0.6
    volume = pd.Series(1_000_000.0, index=idx)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_trade_replay_learns_from_post_trade_future_only():
    df = _df()
    ep = SimpleNamespace(
        entry_trade_id=1,
        asset="crypto",
        exchange="bybit",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        side="buy",
        strategy="trend",
        regime="TREND_UP",
        entry_at=df.index[450].to_pydatetime(),
        exit_at=df.index[470].to_pydatetime(),
        entry_quantity=1.0,
        entry_price=float(df.close.iloc[450]),
        exit_price=float(df.close.iloc[470]),
        net_pnl=100.0,
    )
    result = replay_trade_episode(df, ep, cfg=StrategyConfig(), costs_bps=7.5)
    assert result["future_data_used_only_for_post_trade_learning"] is True
    assert result["bars_held"] == 20
    assert len(result["counterfactuals"]) >= 5
    assert result["best_counterfactual_strategy"] in {"trend", "momentum", "breakout", "mean_reversion", "ensemble"}
    assert "market_flow" in result
    assert "mfe_bps" in result and "mae_bps" in result
