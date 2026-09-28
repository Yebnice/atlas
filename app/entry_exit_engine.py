from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd

from .strategy_engine import _atr, _adx, _rsi
from .config import settings


@dataclass(frozen=True)
class EntryExitConfig:
    """Deterministic trade-plan rules used after the research/AI safety gate.

    The engine never enters without an explicit entry, stop and target. AI may
    veto an unsafe setup, but it cannot invent levels or authorize a trade.
    """
    trend_fast: int = 50
    trend_slow: int = 200
    breakout_lookback: int = 20
    pullback_lookback: int = 10
    atr_period: int = 14
    entry_buffer_atr: float = 0.10
    stop_atr: float = 1.50
    min_reward_risk: float = 2.00
    target_r: float = 2.50
    trail_atr: float = 2.00
    min_adx: float = 18.0
    min_signal: float = 0.25
    max_spread_bps: float = 25.0


def _safe_float(x, default=np.nan):
    try:
        x = float(x)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _trend(close: pd.Series, fast: int, slow: int) -> pd.Series:
    f = close.ewm(span=fast, adjust=False).mean()
    s = close.ewm(span=slow, adjust=False).mean()
    return np.tanh((f / s - 1.0) / 0.008).clip(-1, 1)


def gated_entry_exit_analysis(df: pd.DataFrame, config: EntryExitConfig | None = None) -> pd.DataFrame:
    """Create a deterministic entry/exit plan on each completed bar.

    Direction comes from trend + momentum. Entry is a prior-range breakout with
    an ATR buffer. Stop is volatility/structure based. Target is R-multiple based.
    All values at bar t are tradable only on bar t+1 in the backtest.
    """
    cfg = config or EntryExitConfig()
    if len(df) < max(cfg.trend_slow, cfg.breakout_lookback, cfg.atr_period) + 10:
        raise RuntimeError("Insufficient history for gated entry/exit analysis")

    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    atr = _atr(df, cfg.atr_period)
    adx = _adx(df, cfg.atr_period)
    rsi = _rsi(c, cfg.atr_period)
    trend = _trend(c, cfg.trend_fast, cfg.trend_slow)
    momentum = np.tanh(c.pct_change(min(20, max(5, cfg.pullback_lookback * 2))) / 0.02)

    prior_high = h.shift(1).rolling(cfg.breakout_lookback).max()
    prior_low = l.shift(1).rolling(cfg.breakout_lookback).min()
    prior_swing_low = l.shift(1).rolling(cfg.pullback_lookback).min()
    prior_swing_high = h.shift(1).rolling(cfg.pullback_lookback).max()

    long_trigger = c > prior_high + cfg.entry_buffer_atr * atr
    short_trigger = c < prior_low - cfg.entry_buffer_atr * atr
    long_ok = (trend >= cfg.min_signal) & (momentum > 0) & (adx >= cfg.min_adx) & (rsi >= 50)
    short_ok = (trend <= -cfg.min_signal) & (momentum < 0) & (adx >= cfg.min_adx) & (rsi <= 50)

    side = pd.Series("flat", index=df.index, dtype="object")
    side = side.mask(long_trigger & long_ok, "buy")
    side = side.mask(short_trigger & short_ok, "sell")

    entry = pd.Series(np.nan, index=df.index)
    stop = pd.Series(np.nan, index=df.index)
    target = pd.Series(np.nan, index=df.index)
    risk = pd.Series(np.nan, index=df.index)

    long_entry = c + cfg.entry_buffer_atr * atr
    short_entry = c - cfg.entry_buffer_atr * atr
    long_stop = np.minimum(prior_swing_low, c - cfg.stop_atr * atr)
    short_stop = np.maximum(prior_swing_high, c + cfg.stop_atr * atr)

    entry = entry.mask(side == "buy", long_entry)
    entry = entry.mask(side == "sell", short_entry)
    stop = stop.mask(side == "buy", long_stop)
    stop = stop.mask(side == "sell", short_stop)
    risk = (entry - stop).abs()
    target = target.mask(side == "buy", entry + cfg.target_r * risk)
    target = target.mask(side == "sell", entry - cfg.target_r * risk)

    rr = (target - entry).abs() / risk.replace(0, np.nan)
    safe = (
        side.ne("flat") & entry.notna() & stop.notna() & target.notna() &
        (risk > 0) & (rr >= cfg.min_reward_risk) &
        np.isfinite(entry) & np.isfinite(stop) & np.isfinite(target)
    )
    side = side.where(safe, "flat")

    out = pd.DataFrame(index=df.index)
    out["side"] = side
    out["trend_score"] = trend
    out["momentum_score"] = momentum
    out["adx"] = adx
    out["rsi"] = rsi
    out["atr"] = atr
    out["breakout_high"] = prior_high
    out["breakout_low"] = prior_low
    out["entry_price"] = entry.where(safe)
    out["stop_loss_price"] = stop.where(safe)
    out["take_profit_price"] = target.where(safe)
    out["risk_per_unit"] = risk.where(safe)
    out["reward_risk"] = rr.where(safe)
    out["entry_valid"] = safe
    out["exit_rule"] = "initial structural/ATR stop + configured R target; ATR trailing after +1R; exit on validated opposite signal"
    out["execution_rule"] = "signal formed on completed bar; order eligible on next bar; no same-bar look-ahead"
    return out.replace([np.inf, -np.inf], np.nan)


def start_bot_decision(
    df: pd.DataFrame,
    config: EntryExitConfig | None = None,
    *,
    ai_safe: bool = True,
    data_safe: bool = True,
    spread_bps: float | None = None,
) -> dict:
    """Single customer-facing gate: SAFE => trade plan, otherwise NO_TRADE."""
    cfg = config or EntryExitConfig()
    a = gated_entry_exit_analysis(df, cfg)
    row = a.iloc[-1]
    reasons: list[str] = []
    if not data_safe:
        reasons.append("market_data_gate_failed")
    if spread_bps is not None and spread_bps > cfg.max_spread_bps:
        reasons.append("spread_too_wide")
    if not bool(ai_safe):
        reasons.append("ai_safety_review_failed")
    if not bool(row["entry_valid"]):
        reasons.append("entry_setup_not_confirmed")
    for name in ("entry_price", "stop_loss_price", "take_profit_price"):
        if not np.isfinite(_safe_float(row[name])):
            reasons.append(f"missing_{name}")
    if _safe_float(row["reward_risk"], 0.0) < cfg.min_reward_risk:
        reasons.append("reward_risk_below_minimum")

    safe = not reasons
    plan = None
    if safe:
        plan = {
            "side": str(row["side"]),
            "entry_price": float(row["entry_price"]),
            "stop_loss_price": float(row["stop_loss_price"]),
            "take_profit_price": float(row["take_profit_price"]),
            "reward_risk": float(row["reward_risk"]),
            "atr": float(row["atr"]),
        }
    return {
        "decision": "TRADE" if safe else "NO_TRADE",
        "safe": safe,
        "timestamp": a.index[-1].isoformat(),
        "reasons": reasons,
        "trade_plan": plan,
        "rules": asdict(cfg),
        "ai_role": "safety/context veto only; deterministic engine owns entry, stop and target",
    }


def gated_entry_exit_backtest(
    df: pd.DataFrame,
    config: EntryExitConfig | None = None,
    taker_bps: float = 5.5,
    slippage_bps: float = 2.0,
    initial_equity: float = 1.0,
    risk_fraction: float = 0.005,
    max_leverage: float = 3.0,
    max_notional: float | None = None,
) -> dict:
    """Execution-aware backtest with risk sizing, real entry fills and ATR trailing exits.

    Signals are generated only from completed bar t. A stop/limit entry is eligible on
    t+1 and fills only when that bar actually reaches the entry level. Gap-through fills
    use the bar open. If a filled bar touches both stop and target, stop wins conservatively.
    The trailing stop activates after +1R and never moves away from the trade.
    """
    cfg = config or EntryExitConfig()
    if initial_equity <= 0 or not 0 < risk_fraction <= 0.02 or max_leverage <= 0:
        raise ValueError("Invalid backtest capital/risk configuration")
    a = gated_entry_exit_analysis(df, cfg)
    equity = float(initial_equity)
    peak = equity
    max_dd = 0.0
    trades: list[dict] = []
    ambiguous_bars = 0
    position = None
    # Backtests must apply the same entry-frequency discipline as execution so
    # historical results do not assume unlimited re-entry.
    discipline_day = None
    discipline_entries_today = 0
    last_entry_time = None
    n = len(df)
    fee_rate = taker_bps / 10_000.0
    slip_rate = slippage_bps / 10_000.0

    def _entry_fill(bar, side: str, requested: float) -> float | None:
        o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])
        if side == "buy":
            if h < requested:
                return None
            raw = max(requested, o)  # stop order gaps to the open
            return raw * (1.0 + slip_rate)
        if l > requested:
            return None
        raw = min(requested, o)
        return raw * (1.0 - slip_rate)

    for i in range(1, n):
        bar = df.iloc[i]
        prev = a.iloc[i - 1]

        # Manage an existing filled position first.
        if position is not None:
            side = position["side"]
            stop = position["stop"]
            target = position["target"]
            entry = position["entry"]
            risk_per_unit = position["initial_risk"]
            atr = float(a.iloc[i - 1]["atr"]) if np.isfinite(_safe_float(a.iloc[i - 1]["atr"])) else 0.0
            prev_bar = df.iloc[i - 1]
            high = float(bar["high"])
            low = float(bar["low"])

            # Trail is computed only from the fully completed prior bar. It can affect
            # the current bar, but current-bar close/high/low never influence its own stop.
            if side == "buy" and float(prev_bar["high"]) >= entry + risk_per_unit:
                position["trail_active"] = True
            elif side == "sell" and float(prev_bar["low"]) <= entry - risk_per_unit:
                position["trail_active"] = True
            if position["trail_active"] and atr > 0:
                if side == "buy":
                    position["stop"] = max(position["stop"], float(prev_bar["close"]) - cfg.trail_atr * atr)
                else:
                    position["stop"] = min(position["stop"], float(prev_bar["close"]) + cfg.trail_atr * atr)
                stop = position["stop"]

            hit_stop = low <= stop if side == "buy" else high >= stop
            hit_target = high >= target if side == "buy" else low <= target
            exit_price = None
            reason = None
            if hit_stop and hit_target:
                ambiguous_bars += 1
            if hit_stop:
                exit_price, reason = stop, "stop_loss"
            elif hit_target:
                exit_price, reason = target, "take_profit"
            elif side == "buy" and prev["side"] == "sell":
                exit_price, reason = float(bar["open"]), "opposite_signal"
            elif side == "sell" and prev["side"] == "buy":
                exit_price, reason = float(bar["open"]), "opposite_signal"

            if exit_price is not None:
                exit_fill = exit_price * (1.0 - slip_rate if side == "buy" else 1.0 + slip_rate)
                qty = position["quantity"]
                gross_pnl = qty * (exit_fill - entry) if side == "buy" else qty * (entry - exit_fill)
                exit_fee = abs(qty * exit_fill) * fee_rate
                net_pnl = gross_pnl - exit_fee - position["entry_fee"]
                equity = max(0.0, equity + net_pnl)
                trades.append({
                    **position,
                    "stop": float(stop),
                    "exit": float(exit_fill),
                    "reason": reason,
                    "gross_pnl": float(gross_pnl),
                    "fees": float(position["entry_fee"] + exit_fee),
                    "net_pnl": float(net_pnl),
                    "net_return": float(net_pnl / max(position["equity_before"], 1e-12)),
                })
                position = None

        # Generate/fill a new entry only if the next bar actually reaches the requested price.
        if position is None and bool(prev["entry_valid"]):
            current_time = a.index[i]
            current_day = current_time.date() if hasattr(current_time, "date") else None
            if current_day != discipline_day:
                discipline_day = current_day
                discipline_entries_today = 0
            if settings.discipline_enabled and discipline_entries_today >= settings.discipline_max_entries_per_day:
                continue
            if settings.discipline_enabled and last_entry_time is not None:
                elapsed = (current_time - last_entry_time).total_seconds()
                if elapsed < settings.discipline_entry_cooldown_seconds:
                    continue
            requested = float(prev["entry_price"])
            side = str(prev["side"])
            fill = _entry_fill(bar, side, requested)
            if fill is not None:
                stop = float(prev["stop_loss_price"])
                target = float(prev["take_profit_price"])
                initial_risk = abs(fill - stop)
                if initial_risk > 0 and ((side == "buy" and stop < fill < target) or (side == "sell" and target < fill < stop)):
                    risk_cash = equity * risk_fraction
                    qty = risk_cash / initial_risk
                    if max_notional is not None:
                        qty = min(qty, max_notional / max(fill, 1e-12))
                    qty = min(qty, equity * max_leverage / max(fill, 1e-12))
                    if qty > 0:
                        if settings.discipline_enabled and settings.discipline_enforce_risk_per_trade:
                            risk_cash = initial_risk * qty
                            allowed_risk = equity * risk_fraction * (1.0 + settings.discipline_risk_tolerance)
                            if risk_cash > allowed_risk + 1e-12:
                                continue
                        entry_fee = abs(qty * fill) * fee_rate
                        equity_before = equity
                        position = {
                            "entry_time": a.index[i].isoformat(),
                            "signal_time": a.index[i - 1].isoformat(),
                            "side": side,
                            "requested_entry": requested,
                            "entry": float(fill),
                            "stop": stop,
                            "target": target,
                            "initial_risk": initial_risk,
                            "rr": float(prev["reward_risk"]),
                            "quantity": float(qty),
                            "entry_fee": float(entry_fee),
                            "equity_before": float(equity_before),
                            "trail_active": False,
                        }
                        discipline_entries_today += 1
                        last_entry_time = a.index[i]
                        # Conservative same-bar post-entry protection.
                        hit_stop = float(bar["low"]) <= stop if side == "buy" else float(bar["high"]) >= stop
                        hit_target = float(bar["high"]) >= target if side == "buy" else float(bar["low"]) <= target
                        if hit_stop or hit_target:
                            if hit_stop and hit_target:
                                ambiguous_bars += 1
                            exit_price = stop if hit_stop else target
                            exit_fill = exit_price * (1.0 - slip_rate if side == "buy" else 1.0 + slip_rate)
                            gross_pnl = qty * (exit_fill - fill) if side == "buy" else qty * (fill - exit_fill)
                            exit_fee = abs(qty * exit_fill) * fee_rate
                            net_pnl = gross_pnl - exit_fee - entry_fee
                            equity = max(0.0, equity_before + net_pnl)
                            trades.append({**position, "exit": float(exit_fill), "reason": "stop_loss" if hit_stop else "take_profit",
                                           "gross_pnl": float(gross_pnl), "fees": float(entry_fee + exit_fee),
                                           "net_pnl": float(net_pnl), "net_return": float(net_pnl / max(equity_before, 1e-12))})
                            position = None

        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0 if peak else 0.0)

    if position is not None:
        last = float(df["close"].iloc[-1])
        side = position["side"]
        exit_fill = last * (1.0 - slip_rate if side == "buy" else 1.0 + slip_rate)
        qty = position["quantity"]
        gross_pnl = qty * (exit_fill - position["entry"]) if side == "buy" else qty * (position["entry"] - exit_fill)
        exit_fee = abs(qty * exit_fill) * fee_rate
        net_pnl = gross_pnl - exit_fee - position["entry_fee"]
        equity = max(0.0, equity + net_pnl)
        trades.append({**position, "exit": last, "reason": "end_of_test", "gross_pnl": float(gross_pnl),
                       "fees": float(position["entry_fee"] + exit_fee), "net_pnl": float(net_pnl),
                       "net_return": float(net_pnl / max(position["equity_before"], 1e-12))})
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0 if peak else 0.0)

    rets = pd.Series([t["net_return"] for t in trades], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    avg = float(rets.mean()) if len(rets) else 0.0
    std = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    trade_sharpe = avg / std * np.sqrt(len(rets)) if std > 0 else 0.0
    return {
        "strategy": "gated_breakout_trend_entry_exit_v2",
        "bars": int(n),
        "trades": int(len(trades)),
        "initial_equity": float(initial_equity),
        "final_equity": float(equity),
        "total_return": float(equity / initial_equity - 1.0),
        "max_drawdown": float(max_dd),
        "trade_sharpe": float(trade_sharpe),
        "hit_rate": float((rets > 0).mean()) if len(rets) else 0.0,
        "profit_factor": float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else (float("inf") if len(wins) else 0.0),
        "avg_reward_risk": float(np.mean([t["rr"] for t in trades])) if trades else 0.0,
        "risk_fraction_per_trade": float(risk_fraction),
        "max_leverage": float(max_leverage),
        "transaction_cost_bps_round_trip": float(2 * (taker_bps + slippage_bps)),
        "config": asdict(cfg),
        "execution_model": "next-bar reached-entry fill; gap-through at open; conservative stop-first; ATR trail after +1R",
        "ambiguous_bar_count": int(ambiguous_bars),
        "ambiguous_bar_policy": "STOP_FIRST",
        "trades_detail": trades,
    }
