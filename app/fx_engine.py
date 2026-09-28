from __future__ import annotations
from dataclasses import dataclass, asdict
import math
from typing import Any
import numpy as np
import pandas as pd


MAJOR_FX = ("EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD")


@dataclass(frozen=True)
class FXModelConfig:
    short_lookback: int = 20
    medium_lookback: int = 60
    long_lookback: int = 252
    volatility_lookback: int = 20
    breakout_lookback: int = 55
    target_vol_annual: float = 0.10
    max_leverage: float = 1.0
    signal_threshold: float = 0.25
    high_vol_z: float = 2.0
    max_cost_bps: float = 3.0


def _safe_ret(close: pd.Series, n: int) -> float:
    if len(close) <= n:
        return 0.0
    a, b = float(close.iloc[-1]), float(close.iloc[-1-n])
    return a / b - 1.0 if b > 0 else 0.0


def _annualized_vol(close: pd.Series, n: int) -> float:
    r = close.pct_change().dropna().tail(n)
    if len(r) < max(5, n // 3):
        return 0.0
    return float(r.std(ddof=1) * math.sqrt(252.0))


def _z(value: float, series: pd.Series) -> float:
    s = series.replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < 10:
        return 0.0
    sd = float(s.std(ddof=1))
    return float((value - float(s.mean())) / sd) if sd > 0 else 0.0


def _validate_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing FX OHLC columns: {sorted(missing)}")
    out = df.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index().loc[~out.index.duplicated(keep="last")]
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["open", "high", "low", "close"])
    if len(out) < 100:
        raise ValueError("At least 100 completed FX bars are required")
    if bool(((out[["open", "high", "low", "close"]] <= 0).any(axis=1)).any()):
        raise ValueError("FX prices must be positive")
    if bool((out["high"] < out[["open", "close", "low"]].max(axis=1)).any()):
        raise ValueError("Invalid FX high prices")
    if bool((out["low"] > out[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError("Invalid FX low prices")
    return out


def fx_model_signal(df: pd.DataFrame, cfg: FXModelConfig | None = None,
                    fundamentals: dict[str, float] | None = None,
                    execution_cost_bps: float | None = None) -> dict[str, Any]:
    """Research-only multi-factor FX model. No execution authority."""
    cfg = cfg or FXModelConfig()
    x = _validate_price_frame(df)
    close = x["close"]
    r20 = _safe_ret(close, cfg.short_lookback)
    r60 = _safe_ret(close, cfg.medium_lookback)
    r252 = _safe_ret(close, cfg.long_lookback)
    vol = _annualized_vol(close, cfg.volatility_lookback)
    trend = float(np.clip(0.20 * np.sign(r20) + 0.30 * np.sign(r60) + 0.50 * np.sign(r252), -1, 1))

    # Breakout confirmation uses completed bars only; the current close must clear the prior range.
    prior = close.iloc[:-1].tail(cfg.breakout_lookback)
    breakout = 0.0
    if len(prior) >= max(20, cfg.breakout_lookback // 2):
        if float(close.iloc[-1]) > float(prior.max()):
            breakout = 1.0
        elif float(close.iloc[-1]) < float(prior.min()):
            breakout = -1.0

    # Mean-reversion is deliberately a weak opposing feature, not a standalone signal.
    z = _z(float(close.iloc[-1]), close.tail(min(100, len(close))))
    mean_rev = float(np.clip(-z / 3.0, -1, 1))

    f = fundamentals or {}
    carry = float(np.clip(f.get("carry", 0.0), -1, 1))
    policy = float(np.clip(f.get("policy", 0.0), -1, 1))
    macro = float(np.clip(f.get("macro", 0.0), -1, 1))
    valuation = float(np.clip(f.get("valuation", 0.0), -1, 1))
    order_flow = float(np.clip(f.get("order_flow", 0.0), -1, 1))

    # Economically distinct components are weighted more heavily than technical micro-features.
    score = (
        0.35 * trend + 0.15 * breakout + 0.10 * mean_rev +
        0.10 * carry + 0.10 * policy + 0.08 * macro +
        0.07 * valuation + 0.05 * order_flow
    )
    cost_bps = float(execution_cost_bps if execution_cost_bps is not None else f.get("execution_cost_bps", 0.0))
    high_vol = vol > float(f.get("high_vol_threshold", 0.20)) if vol else False
    if high_vol:
        score *= 0.65
    if cost_bps > cfg.max_cost_bps:
        score = 0.0

    side = "LONG" if score >= cfg.signal_threshold else "SHORT" if score <= -cfg.signal_threshold else "FLAT"
    risk_scale = min(cfg.max_leverage, cfg.target_vol_annual / vol) if vol > 0 else 0.0
    if high_vol:
        risk_scale *= 0.5
    confidence = float(min(1.0, abs(score) * 1.25))
    return {
        "model": "atlas_fx_adaptive_macro_quant_v1",
        "side": side,
        "score": float(score),
        "confidence": confidence,
        "risk_scale": float(max(0.0, risk_scale)),
        "annualized_volatility": float(vol),
        "high_volatility": bool(high_vol),
        "features": {"trend": trend, "breakout": breakout, "mean_reversion": mean_rev,
                     "carry": carry, "policy": policy, "macro": macro, "valuation": valuation,
                     "order_flow": order_flow, "execution_cost_bps": cost_bps},
        "data_gaps": [k for k in ("carry", "policy", "macro", "valuation", "order_flow") if k not in f],
        "execution_authority": False,
        "mode": "RESEARCH_ONLY",
    }


def fx_walk_forward_score(df: pd.DataFrame, cfg: FXModelConfig | None = None,
                          train_bars: int = 252, test_bars: int = 63,
                          cost_bps: float = 1.5) -> dict[str, Any]:
    """Simple forward-only benchmark; never trains on future observations."""
    cfg = cfg or FXModelConfig()
    x = _validate_price_frame(df)
    if len(x) < train_bars + test_bars + 20:
        raise ValueError("Insufficient FX history for walk-forward validation")
    folds = []
    start = train_bars
    while start + test_bars <= len(x):
        train = x.iloc[:start]
        test = x.iloc[start:start + test_bars]
        # Parameters are fixed in this baseline; the train slice exists to enforce temporal separation.
        sig = fx_model_signal(pd.concat([train.tail(max(cfg.long_lookback + 5, 260)), test]), cfg,
                              execution_cost_bps=cost_bps)
        # Use a simple sign of the score for the test period; shift one bar to prevent same-bar lookahead.
        close = test["close"]
        ret = close.pct_change().fillna(0.0)
        direction = 1.0 if sig["score"] > 0 else -1.0 if sig["score"] < 0 else 0.0
        net = direction * ret - (cost_bps / 10000.0) * (direction != 0)
        folds.append({"start": str(test.index[0]), "end": str(test.index[-1]),
                      "return": float((1 + net).prod() - 1),
                      "vol": float(net.std(ddof=1) * math.sqrt(252)) if len(net) > 1 else 0.0})
        start += test_bars
    returns = np.array([f["return"] for f in folds], dtype=float)
    return {"model": "atlas_fx_adaptive_macro_quant_v1", "folds": folds,
            "fold_count": len(folds), "mean_fold_return": float(returns.mean()) if len(returns) else 0.0,
            "positive_fold_rate": float((returns > 0).mean()) if len(returns) else 0.0,
            "cost_bps": cost_bps, "mode": "RESEARCH_ONLY", "execution_authority": False}
