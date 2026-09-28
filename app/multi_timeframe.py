from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd

from .strategy_engine import _atr, _adx, _rsi


@dataclass(frozen=True)
class MultiTimeframeConfig:
    regime_fast: int = 20
    regime_slow: int = 50
    setup_lookback: int = 20
    confirmation_lookback: int = 12
    atr_period: int = 14
    entry_buffer_atr: float = 0.10
    stop_atr: float = 1.8
    take_profit_atr: float = 3.0
    min_regime_score: float = 0.15


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    return df.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["open", "high", "low", "close"])


def _trend_score(frame: pd.DataFrame, cfg: MultiTimeframeConfig) -> pd.Series:
    fast = frame.close.ewm(span=cfg.regime_fast, adjust=False).mean()
    slow = frame.close.ewm(span=cfg.regime_slow, adjust=False).mean()
    return np.tanh((fast / slow - 1.0) / 0.008).clip(-1, 1)


def _map_back(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    # Conservative availability rule: a higher-timeframe observation becomes usable
    # only after the NEXT base-bar boundary. This makes the research path robust even
    # when callers evaluate a signal on the exact higher-timeframe close timestamp.
    shifted = series.shift(1)
    merged = shifted.reindex(index.union(shifted.index)).sort_index().ffill()
    return merged.reindex(index)


def multi_timeframe_analysis(df: pd.DataFrame, config: MultiTimeframeConfig | None = None) -> pd.DataFrame:
    """Analyze 4H/1H regime, 15M setup, and 5M entry confirmation.

    All higher-timeframe features are mapped only after their bars close. The
    returned entry/stop/target values are candidate levels, not orders.
    """
    cfg = config or MultiTimeframeConfig()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    base = df.copy()
    base.index = idx

    h4 = _resample_ohlcv(base, "4h")
    h1 = _resample_ohlcv(base, "1h")
    m15 = _resample_ohlcv(base, "15min")
    m5 = _resample_ohlcv(base, "5min")

    regime4 = _trend_score(h4, cfg)
    regime1 = _trend_score(h1, cfg)
    adx1 = _adx(h1, cfg.atr_period)

    setup_high = m15.high.shift(1).rolling(cfg.setup_lookback).max()
    setup_low = m15.low.shift(1).rolling(cfg.setup_lookback).min()
    setup_mid = (setup_high + setup_low) / 2
    setup_trend = _trend_score(m15, cfg)
    setup_break = np.where(m15.close > setup_high, 1.0, np.where(m15.close < setup_low, -1.0, 0.0))

    m5_atr = _atr(m5, cfg.atr_period)
    m5_fast = m5.close.ewm(span=9, adjust=False).mean()
    m5_slow = m5.close.ewm(span=21, adjust=False).mean()
    m5_momentum = np.tanh(m5.close.pct_change(cfg.confirmation_lookback) / 0.015)
    m5_rsi = _rsi(m5.close, 14)
    confirm_trend = np.tanh(((m5_fast / m5_slow) - 1.0) / 0.003)
    confirm = (0.55 * confirm_trend + 0.30 * m5_momentum + 0.15 * ((m5_rsi - 50) / 20)).clip(-1, 1)

    out = pd.DataFrame(index=idx)
    out["regime_4h"] = _map_back(regime4, idx)
    out["regime_1h"] = _map_back(regime1, idx)
    out["adx_1h"] = _map_back(adx1, idx)
    out["setup_15m"] = _map_back(pd.Series(setup_trend, index=m15.index), idx)
    out["setup_breakout_15m"] = _map_back(pd.Series(setup_break, index=m15.index), idx)
    out["setup_high_15m"] = _map_back(setup_high, idx)
    out["setup_low_15m"] = _map_back(setup_low, idx)
    out["setup_mid_15m"] = _map_back(setup_mid, idx)
    out["confirm_5m"] = _map_back(confirm, idx)
    out["atr_5m"] = _map_back(m5_atr, idx)

    aligned_direction = np.sign(out["regime_4h"] + out["regime_1h"] + out["setup_15m"])
    strength = (out["regime_4h"].abs() + out["regime_1h"].abs()) / 2
    aligned = (np.sign(out["regime_4h"]) == np.sign(out["regime_1h"])) & (strength >= cfg.min_regime_score)
    breakout_ok = out["setup_breakout_15m"] == aligned_direction
    confirm_ok = np.sign(out["confirm_5m"]) == aligned_direction
    out["mtf_direction"] = aligned_direction.where(aligned, 0.0)
    out["entry_confirmed"] = aligned & breakout_ok & confirm_ok & (out["confirm_5m"].abs() >= 0.20)

    price = base["close"].astype(float)
    atr = out["atr_5m"]
    long_entry = out["setup_high_15m"] + cfg.entry_buffer_atr * atr
    short_entry = out["setup_low_15m"] - cfg.entry_buffer_atr * atr
    out["entry_price"] = np.where(out["mtf_direction"] > 0, long_entry, np.where(out["mtf_direction"] < 0, short_entry, price))
    out["stop_price"] = np.where(
        out["mtf_direction"] > 0, out["entry_price"] - cfg.stop_atr * atr,
        np.where(out["mtf_direction"] < 0, out["entry_price"] + cfg.stop_atr * atr, np.nan),
    )
    out["take_profit_price"] = np.where(
        out["mtf_direction"] > 0, out["entry_price"] + cfg.take_profit_atr * atr,
        np.where(out["mtf_direction"] < 0, out["entry_price"] - cfg.take_profit_atr * atr, np.nan),
    )
    out["entry_rule"] = "4H+1H aligned regime; 15M structure breakout; 5M confirmation; execute next bar"
    out["exit_rule"] = "ATR stop/target, structure invalidation, or higher-timeframe direction flip"
    return out.replace([np.inf, -np.inf], np.nan)


def multi_timeframe_signal(df: pd.DataFrame, config: MultiTimeframeConfig | None = None) -> dict:
    cfg = config or MultiTimeframeConfig()
    a = multi_timeframe_analysis(df, cfg).dropna(subset=["mtf_direction", "atr_5m"])
    if a.empty:
        raise RuntimeError("Insufficient history for multi-timeframe analysis")
    row = a.iloc[-1]
    direction = float(row["mtf_direction"])
    confirmed = bool(row["entry_confirmed"])
    side = "buy" if direction > 0 and confirmed else ("sell" if direction < 0 and confirmed else "flat")
    return {
        "strategy_version": "mtf-4h-1h-15m-5m-v1",
        "signal_timestamp": a.index[-1].isoformat(),
        "strategy": "multi_timeframe_structure",
        "side": side,
        "confirmed": confirmed,
        "regime_4h": float(row["regime_4h"]),
        "regime_1h": float(row["regime_1h"]),
        "adx_1h": float(row["adx_1h"]),
        "setup_15m": float(row["setup_15m"]),
        "setup_breakout_15m": float(row["setup_breakout_15m"]),
        "confirmation_5m": float(row["confirm_5m"]),
        "entry_price": float(row["entry_price"]) if np.isfinite(row["entry_price"]) else None,
        "stop_loss_price": float(row["stop_price"]) if np.isfinite(row["stop_price"]) else None,
        "take_profit_price": float(row["take_profit_price"]) if np.isfinite(row["take_profit_price"]) else None,
        "entry_rule": row["entry_rule"],
        "exit_rule": row["exit_rule"],
        "execution_mode": "PAPER_SHADOW_ONLY",
        "config": asdict(cfg),
    }
