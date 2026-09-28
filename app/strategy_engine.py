from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategyConfig:
    trend_fast: int = 50
    trend_slow: int = 200
    momentum_lookback: int = 72
    breakout_lookback: int = 55
    mean_reversion_lookback: int = 20
    mean_reversion_z: float = 2.0
    atr_period: int = 14
    target_vol_annual: float = 0.15
    max_leverage: float = 1.5
    signal_threshold: float = 0.20
    stop_atr: float = 2.5
    take_profit_atr: float = 4.0


def _annualization_factor(index: pd.Index, asset: str = "crypto") -> float:
    """Estimate periods/year from bar spacing and the asset's trading calendar class.

    Crypto is treated as 24/7. Forex/commodity research uses ~252 active trading
    days rather than incorrectly annualizing every dataset as 365 calendar days.
    The result remains an approximation and is reported with the backtest.
    """
    if len(index) < 3 or not isinstance(index, pd.DatetimeIndex):
        return 252.0
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    seconds = idx.to_series().diff().dt.total_seconds().dropna()
    seconds = seconds[(seconds > 0) & np.isfinite(seconds)]
    if seconds.empty:
        return 252.0
    median_seconds = float(seconds.median())
    days_per_year = 365.25 if str(asset).lower() == "crypto" else 252.0
    return float(np.clip((days_per_year * 24 * 3600) / median_seconds, 1.0, 1_000_000.0))


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _zscore(s: pd.Series, n: int) -> pd.Series:
    m = s.rolling(n).mean()
    sd = s.rolling(n).std().replace(0, np.nan)
    return (s - m) / sd


def strategy_signals(df: pd.DataFrame, config: StrategyConfig | None = None, asset: str = "crypto") -> pd.DataFrame:
    """Generate independent, explainable strategy signals.

    Values are in [-1, 1]. Signals are deliberately lagged by the caller during
    backtests so the current bar cannot trade on its own close.
    """
    cfg = config or StrategyConfig()
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)

    out = pd.DataFrame(index=df.index)
    fast = c.ewm(span=cfg.trend_fast, adjust=False).mean()
    slow = c.ewm(span=cfg.trend_slow, adjust=False).mean()
    trend = np.tanh(((fast / slow) - 1.0) / 0.01)

    log_mom = np.log(c).diff(cfg.momentum_lookback)
    mom_scale = np.log(c).diff().rolling(cfg.momentum_lookback).std() * np.sqrt(max(cfg.momentum_lookback, 1))
    momentum = np.tanh(log_mom / mom_scale.replace(0, np.nan))

    prior_high = h.shift(1).rolling(cfg.breakout_lookback).max()
    prior_low = l.shift(1).rolling(cfg.breakout_lookback).min()
    breakout = pd.Series(0.0, index=df.index)
    breakout = breakout.mask(c > prior_high, 1.0)
    breakout = breakout.mask(c < prior_low, -1.0)

    z = _zscore(c, cfg.mean_reversion_lookback)
    # Mean reversion is only enabled away from a strong trend; this avoids
    # repeatedly fading persistent directional moves.
    regime = (fast / slow - 1.0).abs()
    mr = (-z / cfg.mean_reversion_z).clip(-1.0, 1.0)
    mr = mr.where(regime < 0.01, 0.0)

    out["trend"] = trend.clip(-1, 1)
    out["momentum"] = momentum.clip(-1, 1)
    out["breakout"] = breakout
    out["mean_reversion"] = mr
    # Ensemble weights emphasize robust directional signals while retaining
    # mean reversion as a diversifier rather than letting it dominate.
    adx = _adx(df, cfg.atr_period)
    rsi = _rsi(c, cfg.mean_reversion_lookback)
    macd_fast = c.ewm(span=12, adjust=False).mean()
    macd_slow = c.ewm(span=26, adjust=False).mean()
    macd = macd_fast - macd_slow
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal
    atr_for_norm = _atr(df, cfg.atr_period).replace(0, np.nan)
    trend_quality = np.tanh((adx - 20.0) / 10.0).clip(0, 1)
    macd_signal_score = np.tanh((macd_hist / atr_for_norm) * 0.5)
    if "volume" in df.columns:
        volume = pd.to_numeric(df["volume"], errors="coerce")
        volume = volume.where(np.isfinite(volume) & (volume > 0))
        utc_idx = pd.DatetimeIndex(df.index)
        if utc_idx.tz is None:
            utc_idx = utc_idx.tz_localize("UTC")
        day_key = utc_idx.tz_convert("UTC").date
        vwap_num = (c * volume).groupby(day_key).cumsum()
        vwap_den = volume.groupby(day_key).cumsum().replace(0, np.nan)
        vwap = vwap_num / vwap_den
        vwap_signal = np.tanh((c / vwap - 1.0) / 0.005)
        vwap_available = vwap.notna()
    else:
        vwap_signal = pd.Series(0.0, index=df.index)
        vwap_available = pd.Series(False, index=df.index)
    out["adx"] = adx
    out["rsi"] = rsi
    out["macd_signal"] = macd_signal_score.clip(-1, 1)
    out["vwap_signal"] = vwap_signal.clip(-1, 1)
    out["trend_quality"] = trend_quality
    out["ensemble"] = (
        0.28 * out["trend"]
        + 0.22 * out["momentum"]
        + 0.18 * out["breakout"]
        + 0.10 * out["mean_reversion"]
        + 0.12 * out["macd_signal"]
        + 0.10 * np.sign(out["trend"]) * trend_quality
    ).clip(-1, 1)
    out["vwap_available"] = vwap_available
    sess = _session_features(df)
    out = out.join(sess)
    # Session-open breakout confirmation: require price to clear the first-hour range.
    out["london_open_breakout"] = np.where(c > out["london_range_high"], 1.0, np.where(c < out["london_range_low"], -1.0, 0.0))
    out["new_york_open_breakout"] = np.where(c > out["new_york_range_high"], 1.0, np.where(c < out["new_york_range_low"], -1.0, 0.0))
    out["atr"] = _atr(df, cfg.atr_period)
    annualization = _annualization_factor(df.index, asset=asset)
    out["realized_vol"] = np.log(c).diff().rolling(20).std() * np.sqrt(annualization)
    out.attrs["annualization_factor"] = annualization
    return out.replace([np.inf, -np.inf], np.nan)


def risk_scaled_position(signal: float, realized_vol: float, config: StrategyConfig | None = None) -> float:
    """Convert an ensemble signal into a volatility-targeted leverage."""
    cfg = config or StrategyConfig()
    if not np.isfinite(signal) or not np.isfinite(realized_vol) or realized_vol <= 0:
        return 0.0
    leverage = cfg.target_vol_annual / realized_vol
    return float(np.clip(signal * leverage, -cfg.max_leverage, cfg.max_leverage))


def strategy_signal(df: pd.DataFrame, config: StrategyConfig | None = None, asset: str = "crypto") -> dict:
    cfg = config or StrategyConfig()
    sig = strategy_signals(df, cfg, asset=asset).dropna(subset=["ensemble", "atr", "realized_vol"])
    if sig.empty:
        raise RuntimeError("Insufficient market history for strategy ensemble")
    row = sig.iloc[-1]
    raw = float(row["ensemble"])
    position = risk_scaled_position(raw, float(row["realized_vol"]), cfg)
    if abs(raw) < cfg.signal_threshold:
        position = 0.0
    price = float(df["close"].iloc[-1])
    atr = float(row["atr"])
    side = "buy" if position > 0 else ("sell" if position < 0 else "flat")
    stop = take = None
    if side == "buy":
        stop, take = price - cfg.stop_atr * atr, price + cfg.take_profit_atr * atr
    elif side == "sell":
        stop, take = price + cfg.stop_atr * atr, price - cfg.take_profit_atr * atr
    return {
        "strategy_version": "session-aware-v1",
        "signal_timestamp": sig.index[-1].isoformat(),
        "strategy": "multi_factor_session_aware",
        "research_evidence_class": "ESTABLISHED_TREND_MOMENTUM_PLUS_HEURISTIC_CONFIRMATIONS",
        "trend_signal": float(row["trend"]),
        "momentum_signal": float(row["momentum"]),
        "breakout_signal": float(row["breakout"]),
        "mean_reversion_signal": float(row["mean_reversion"]),
        "ensemble_score": raw,
        "position_leverage": position,
        "side": side,
        "realized_vol_annual": float(row["realized_vol"]),
        "asset_class": asset,
        "vwap_available": bool(row.get("vwap_available", False)),
        "atr": atr,
        "stop_loss_price": stop,
        "take_profit_price": take,
        "entry_rule": "trend/momentum/breakout evidence; session metrics are diagnostic context; execute next bar only",
        "exit_rule": "ATR levels are protective candidate levels; portfolio backtest also tests signal-based exits; intrabar stop/target fills require execution-aware backtest",
        "session": str(row.get("session", "UNKNOWN")),
        "london_open_breakout": float(row.get("london_open_breakout", 0.0)),
        "new_york_open_breakout": float(row.get("new_york_open_breakout", 0.0)),
        "config": asdict(cfg),
    }


def strategy_backtest(
    df: pd.DataFrame,
    config: StrategyConfig | None = None,
    taker_bps: float = 5.5,
    slippage_bps: float = 2.0,
    asset: str = "crypto",
) -> dict:
    cfg = config or StrategyConfig()
    s = strategy_signals(df, cfg, asset=asset)
    # Shift positions one bar: signals formed on bar t execute on bar t+1.
    raw = s["ensemble"].fillna(0.0)
    vol = s["realized_vol"]
    lev = (cfg.target_vol_annual / vol.replace(0, np.nan)).clip(upper=cfg.max_leverage)
    pos = (raw * lev).clip(-cfg.max_leverage, cfg.max_leverage)
    pos = pos.where(raw.abs() >= cfg.signal_threshold, 0.0).shift(1).fillna(0.0)

    ret = df["close"].pct_change().fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    costs = turnover * ((taker_bps + slippage_bps) / 10_000.0)
    net = pos * ret - costs
    equity = (1.0 + net).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    ann = _annualization_factor(df.index, asset=asset)
    vol_net = float(net.std())
    sharpe = float(net.mean() / vol_net * np.sqrt(ann)) if vol_net > 0 else 0.0
    active = pos != 0
    return {
        "strategy": "trend_momentum_breakout_mean_reversion",
        "backtest_model": "signal_return_with_next_bar_lag_and_transaction_costs; not intrabar stop-target execution",
        "asset_class": asset,
        "bars": int(len(df)),
        "validated_bars": int(s.notna().all(axis=1).sum()),
        "total_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float(drawdown.min()),
        "sharpe": sharpe,
        "trades": int((turnover > 0).sum()),
        "hit_rate": float((net[active] > 0).mean()) if bool(active.any()) else 0.0,
        "average_leverage": float(pos.abs().mean()),
        "max_leverage": float(pos.abs().max()),
        "transaction_cost_bps": float(taker_bps + slippage_bps),
        "annualization_factor": float(ann),
    }


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(~(down == 0), np.where(up > 0, 100.0, 50.0))
    return out


def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _atr(df, n).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1/n, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/n, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()


def _session_features(df: pd.DataFrame) -> pd.DataFrame:
    from .market_sessions import session_state, LONDON, NEW_YORK
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    s = session_state(idx)
    out = pd.DataFrame(index=df.index)
    out["session"] = s["session"].to_numpy()
    out["london_open_window"] = s["london_open_window"].to_numpy()
    out["new_york_open_window"] = s["new_york_open_window"].to_numpy()

    def opening_range(tz, start_min: int, key_prefix: str) -> None:
        local = idx.tz_convert(tz)
        minutes = local.hour * 60 + local.minute
        local_date = local.date
        mask = (minutes >= start_min) & (minutes < start_min + 60)
        # The first-hour high/low is only known after that hour closes. Mapping is
        # deliberately NaN before completion to prevent opening-range look-ahead.
        hi_by_day = df.loc[mask, "high"].groupby(local_date[mask]).max()
        lo_by_day = df.loc[mask, "low"].groupby(local_date[mask]).min()
        hi = pd.Series(local_date, index=df.index).map(hi_by_day)
        lo = pd.Series(local_date, index=df.index).map(lo_by_day)
        completed = minutes >= start_min + 60
        out[f"{key_prefix}_range_high"] = hi.where(completed)
        out[f"{key_prefix}_range_low"] = lo.where(completed)

    opening_range(LONDON, 8 * 60, "london")
    opening_range(NEW_YORK, 9 * 60 + 30, "new_york")
    return out

