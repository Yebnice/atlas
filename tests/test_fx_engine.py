import numpy as np
import pandas as pd
import pytest
from app.fx_engine import FXModelConfig, fx_model_signal, fx_walk_forward_score


def _trend(n=500, up=True):
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    base = np.linspace(1.0, 1.4 if up else 0.7, n)
    close = pd.Series(base, index=idx)
    return pd.DataFrame({"open": close, "high": close*1.002, "low": close*0.998, "close": close, "volume": 1.0})


def test_fx_model_is_research_only_and_detects_trend():
    r = fx_model_signal(_trend())
    assert r["execution_authority"] is False
    assert r["mode"] == "RESEARCH_ONLY"
    assert r["side"] in {"LONG", "FLAT"}
    assert r["features"]["trend"] > 0


def test_fx_model_cost_gate_blocks_expensive_execution():
    r = fx_model_signal(_trend(), execution_cost_bps=100)
    assert r["side"] == "FLAT"
    assert r["score"] == 0.0


def test_fx_model_high_vol_reduces_risk():
    x = _trend(500)
    rng = np.random.default_rng(7)
    shocks = rng.normal(0, 0.03, len(x))
    x["close"] = x["close"].iloc[0] * np.cumprod(1 + shocks)
    x["open"] = x["close"].shift(1).fillna(x["close"])
    x["high"] = x[["open", "close"]].max(axis=1) * 1.01
    x["low"] = x[["open", "close"]].min(axis=1) * 0.99
    r = fx_model_signal(x)
    assert r["annualized_volatility"] > 0
    if r["high_volatility"]:
        assert r["risk_scale"] <= 0.5


def test_fx_walk_forward_is_forward_only():
    r = fx_walk_forward_score(_trend(700), train_bars=300, test_bars=100)
    assert r["fold_count"] == 4
    assert r["execution_authority"] is False


def test_fx_rejects_short_history():
    with pytest.raises(ValueError):
        fx_model_signal(_trend(50))

def test_main_source_exposes_fx_model_endpoint():
    from pathlib import Path
    source = Path("app/main.py").read_text()
    assert '/api/research/fx-model' in source
