import numpy as np
import pandas as pd

from app.trading_core import build_features, triple_barrier, rsi
from app.ids import client_order_id, make_signal_id


def frame(n=500):
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, .01, n))), index=idx)
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * .99, "close": close, "volume": 100}, index=idx)


def test_features_are_nonempty_and_finite():
    f = build_features(frame())
    assert len(f) > 0
    assert list(f.columns)
    assert np.isfinite(f.to_numpy()).all()


def test_constant_volume_does_not_destroy_features():
    f = build_features(frame())
    assert f["vol_z"].notna().all()


def test_rsi_handles_monotonic_price_without_nan_collapse():
    idx = pd.date_range("2025-01-01", periods=100, freq="h", tz="UTC")
    close = pd.Series(np.arange(100.0, 200.0), index=idx)
    out = rsi(close)
    assert out.iloc[-1] == 100.0
    assert out.iloc[-1] > 99


def test_triple_barrier_does_not_label_incomplete_future_window():
    f = frame(100)
    vol = pd.Series(.01, index=f.index)
    y = triple_barrier(f.close, vol, f.high, f.low, max_hold=12)
    assert y.iloc[-12:].isna().all()
    assert set(y.dropna().unique()).issubset({-1.0, 0.0, 1.0})


def test_triple_barrier_same_bar_touch_is_conservative_neutral():
    idx = pd.date_range("2025-01-01", periods=20, freq="h", tz="UTC")
    close = pd.Series(100.0, index=idx)
    vol = pd.Series(.01, index=idx)
    high = close.copy(); low = close.copy()
    high.iloc[1] = 102.5; low.iloc[1] = 97.5
    y = triple_barrier(close, vol, high, low, pt=2.0, sl=2.0, max_hold=5)
    assert y.iloc[0] == 0


def test_signal_id_and_client_order_id_are_deterministic():
    sid = make_signal_id("bybit", "BTC/USDT:USDT", "1h", "2025-01-01T00:00:00+00:00", "buy")
    assert sid == make_signal_id("bybit", "BTC/USDT:USDT", "1h", "2025-01-01T00:00:00+00:00", "buy")
    assert client_order_id(sid) == client_order_id(sid)
    assert client_order_id(sid).startswith("ait-")


def test_training_refuses_collapsed_target():
    from app.trading_core import train_model
    idx = pd.date_range("2025-01-01", periods=1400, freq="h", tz="UTC")
    close = pd.Series(100.0 * np.exp(np.linspace(0, 0.001, len(idx))), index=idx)
    df = pd.DataFrame({"open": close, "high": close * (1 + 1e-7), "low": close * (1 - 1e-7), "close": close,
                       "volume": np.linspace(100, 120, len(idx))}, index=idx)
    try:
        train_model(df, "models/collapsed-test.joblib", min_train=800, folds=2, asset="crypto")
    except RuntimeError as exc:
        assert "two target classes" in str(exc) or "collapsed" in str(exc)
    else:
        raise AssertionError("Training should refuse a collapsed target")
