from __future__ import annotations

"""Regime-aware strategy selection for the adaptive trading bot.

The router is deliberately subordinate to the deterministic risk engine. It only
answers three questions:
  1. What regime is the completed bar in?
  2. Which validated strategy family has the strongest evidence for that regime?
  3. Should the current strategy be held, switched, blended, or abstained?

Selection uses only data at or before the decision bar. Live execution still has
to pass execute_signal()/risk_gate().
"""

from datetime import datetime, timezone
import math
import numpy as np
import pandas as pd

from .strategy_engine import StrategyConfig, strategy_signals
from .research_validation import purged_walk_forward_splits

STRATEGIES = ("trend", "momentum", "breakout", "mean_reversion", "ensemble")
REGIMES = ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", "TRANSITION")


def classify_regime(df: pd.DataFrame, *, asset: str = "crypto") -> pd.Series:
    """Classify each completed bar without using future observations."""
    c = df["close"].astype(float)
    fast = c.ewm(span=50, adjust=False).mean()
    slow = c.ewm(span=200, adjust=False).mean()
    annual = 365.25 if str(asset).lower() == "crypto" else 252.0
    vol = c.pct_change().rolling(20).std() * np.sqrt(annual)
    trend_gap = (fast / slow - 1.0).abs()
    trend = (fast / slow - 1.0)
    regime = pd.Series("RANGE", index=df.index, dtype="object")
    regime = regime.mask(vol >= 0.60, "HIGH_VOL")
    stable_trend = (vol < 0.60) & (trend_gap >= 0.004)
    regime = regime.mask(stable_trend & (trend > 0), "TREND_UP")
    regime = regime.mask(stable_trend & (trend < 0), "TREND_DOWN")
    # A narrow gap with changing trend direction is explicitly treated as a transition
    # rather than pretending the market is cleanly trending or ranging.
    direction = np.sign(trend).replace(0, np.nan).ffill().fillna(0)
    direction_change = direction.diff().abs().fillna(0) > 1
    regime = regime.mask(direction_change & (vol < 0.60), "TRANSITION")
    return regime


def _strategy_returns(df: pd.DataFrame, cfg: StrategyConfig, strategy: str,
                      costs_bps: float, asset: str) -> pd.Series:
    s = strategy_signals(df, cfg, asset=asset)
    raw = s[strategy].fillna(0.0)
    vol = s["realized_vol"]
    lev = (cfg.target_vol_annual / vol.replace(0, np.nan)).clip(upper=cfg.max_leverage)
    pos = (raw * lev).clip(-cfg.max_leverage, cfg.max_leverage)
    pos = pos.where(raw.abs() >= cfg.signal_threshold, 0.0).shift(1).fillna(0.0)
    ret = df["close"].pct_change().fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    return pos * ret - turnover * float(costs_bps) / 10000.0


def _metrics(x: pd.Series) -> dict:
    x = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    if x.empty:
        return {"bars": 0, "trades": 0, "total_return": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "mean_return": 0.0}
    eq = (1.0 + x).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    std = float(x.std())
    sharpe = float(x.mean() / std * math.sqrt(max(len(x), 1))) if std > 0 else 0.0
    return {
        "bars": int(len(x)),
        "trades": int(np.count_nonzero(np.diff(np.r_[0.0, np.sign(x.to_numpy())]))),
        "total_return": float(eq.iloc[-1] - 1.0),
        "sharpe": sharpe,
        "max_drawdown": float(dd.min()),
        "mean_return": float(x.mean()),
    }


def regime_conditioned_strategy_performance(df: pd.DataFrame, cfg: StrategyConfig | None = None,
                                             *, costs_bps: float = 7.5,
                                             asset: str = "crypto") -> dict:
    """Compute per-strategy performance separately inside each market regime."""
    cfg = cfg or StrategyConfig()
    regimes = classify_regime(df, asset=asset)
    result: dict[str, dict] = {}
    for strategy in STRATEGIES:
        returns = _strategy_returns(df, cfg, strategy, costs_bps, asset)
        signal = strategy_signals(df, cfg, asset=asset)[strategy].fillna(0.0)
        positions = signal.where(signal.abs() >= cfg.signal_threshold, 0.0).shift(1).fillna(0.0)
        result[strategy] = {}
        for regime in sorted(set(regimes.dropna().astype(str))):
            mask = regimes == regime
            x = returns.loc[mask]
            m = _metrics(x)
            p = positions.loc[mask]
            m["trades"] = int(np.count_nonzero(np.diff(np.r_[0.0, p.to_numpy()])))
            result[strategy][regime] = m
    return result


def _score_metrics(m: dict, *, min_trades: int = 20) -> float:
    if int(m.get("bars", 0)) < 30:
        return -10.0
    # Evidence is risk-adjusted and deliberately conservative. Drawdown is penalized
    # twice as a stability control; return alone can never dominate the score.
    trades = int(m.get("trades", 0))
    if trades < min_trades:
        return -5.0
    sharpe = float(m.get("sharpe", 0.0))
    ret = float(m.get("total_return", 0.0))
    dd = abs(float(m.get("max_drawdown", 0.0)))
    return sharpe + 0.75 * ret - 1.25 * dd


def _recent_regime_stability(regimes: pd.Series, bars: int = 3) -> tuple[str, int]:
    if regimes.empty:
        return "UNKNOWN", 0
    tail = [str(x) for x in regimes.tail(max(1, int(bars))).tolist()]
    current = tail[-1]
    stable = 0
    for x in reversed(tail):
        if x != current:
            break
        stable += 1
    return current, stable


def online_strategy_scores(
    outcomes,
    *,
    current_regime: str | None = None,
    timeframe: str | None = None,
    half_life_days: float = 14.0,
    min_observations: int = 10,
) -> dict[str, float]:
    """Bounded, regime-aware online experience scores.

    The learner prefers net return in the current regime/timeframe. If there are too
    few observations for that slice it shrinks toward the broader customer/symbol
    experience already supplied by the caller. Future information is never used by
    the live selector: only completed StrategyOutcome rows are accepted here.
    """
    now = datetime.now(timezone.utc)

    def collect(rows):
        grouped: dict[str, list[tuple[float, float]]] = {}
        for row in rows or []:
            strategy = row.get("strategy") if isinstance(row, dict) else getattr(row, "strategy", "")
            if strategy not in STRATEGIES:
                continue
            value = None
            for field in ("net_return_bps", "return_bps"):
                value = row.get(field) if isinstance(row, dict) else getattr(row, field, None)
                if value is not None:
                    break
            if value is None:
                continue
            try:
                value = float(value)
            except Exception:
                continue
            created = row.get("created_at") if isinstance(row, dict) else getattr(row, "created_at", None)
            if created is None:
                age_days = 0.0
            else:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = max(0.0, (now - created).total_seconds() / 86400.0)
            weight = math.pow(0.5, age_days / max(0.25, float(half_life_days)))
            grouped.setdefault(strategy, []).append((value, weight))
        out: dict[str, tuple[float, int]] = {}
        for name, vals in grouped.items():
            den = sum(w for _, w in vals)
            mean_bps = sum(v * w for v, w in vals) / den if den else 0.0
            out[name] = (float(mean_bps), len(vals))
        return out

    global_stats = collect(outcomes)
    regime_rows = []
    if current_regime:
        for row in outcomes or []:
            r = row.get("regime") if isinstance(row, dict) else getattr(row, "regime", None)
            tf = row.get("timeframe") if isinstance(row, dict) else getattr(row, "timeframe", None)
            if str(r or "") == str(current_regime):
                if timeframe and str(tf or timeframe) != str(timeframe):
                    continue
                regime_rows.append(row)
    regime_stats = collect(regime_rows)

    scores = {name: 0.0 for name in STRATEGIES}
    for name in STRATEGIES:
        g_mean, g_n = global_stats.get(name, (0.0, 0))
        r_mean, r_n = regime_stats.get(name, (0.0, 0))
        if r_n >= int(min_observations):
            mean_bps = 0.70 * r_mean + 0.30 * g_mean
        elif g_n >= int(min_observations):
            mean_bps = g_mean
        else:
            mean_bps = 0.0
        scores[name] = float(np.clip(mean_bps / 25.0, -3.0, 3.0))
    return scores


def select_strategy(df: pd.DataFrame, cfg: StrategyConfig | None = None, *,
                    asset: str = "crypto", current_strategy: str | None = None,
                    cooldown_active: bool = False, min_regime_bars: int = 3,
                    switch_min_advantage: float = 0.15, min_trades: int = 20,
                    costs_bps: float = 7.5, online_scores: dict[str, float] | None = None,
                    online_weight: float = 0.25, blend_enabled: bool = True,
                    blend_top_n: int = 3) -> dict:
    """Select/hold/blend using only history up to the previous completed bar.

    The last bar is the decision bar. Historical performance is calculated on
    all preceding bars, so the selector never rewards itself using the bar it is
    about to trade.
    """
    if len(df) < 260:
        return {"status": "INSUFFICIENT_DATA", "strategy": "none", "regime": "UNKNOWN"}
    history = df.iloc[:-1].copy()
    hist_regimes = classify_regime(history, asset=asset)
    current_regime = str(classify_regime(df, asset=asset).iloc[-1])
    _, stable_bars = _recent_regime_stability(classify_regime(df, asset=asset), min_regime_bars)
    if stable_bars < min_regime_bars:
        return {"status": "TRANSITION", "strategy": current_strategy or "none",
                "regime": current_regime, "regime_stable_bars": stable_bars,
                "reason": "regime_not_stable"}

    perf = regime_conditioned_strategy_performance(history, cfg, costs_bps=costs_bps, asset=asset)
    ranked = []
    for name in STRATEGIES:
        m = perf.get(name, {}).get(current_regime, {})
        base = _score_metrics(m, min_trades=min_trades)
        online = float((online_scores or {}).get(name, 0.0))
        score = (1.0 - float(online_weight)) * base + float(online_weight) * online
        ranked.append({"strategy": name, "score": float(score), "historical_score": float(base),
                       "online_score": online, "metrics": m})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    best = ranked[0]
    current_row = next((x for x in ranked if x["strategy"] == current_strategy), None)
    chosen = best["strategy"]
    action = "SELECT"
    if current_row and current_strategy in STRATEGIES:
        advantage = best["score"] - current_row["score"]
        if cooldown_active or advantage < float(switch_min_advantage):
            chosen = current_strategy
            action = "HOLD"
        else:
            action = "SWITCH" if chosen != current_strategy else "HOLD"
    if current_regime == "TRANSITION":
        chosen = current_strategy or chosen
        action = "HOLD" if current_strategy else "ABSTAIN"

    blend = []
    if blend_enabled and action != "ABSTAIN":
        eligible = [x for x in ranked if x["score"] > 0][:max(1, int(blend_top_n))]
        if eligible:
            scores = np.asarray([x["score"] for x in eligible], dtype=float)
            # Stable softmax; never let one weak strategy dominate a strong one by noise.
            scores = scores - np.max(scores)
            weights = np.exp(scores)
            weights = weights / weights.sum()
            blend = [{"strategy": x["strategy"], "weight": float(w), "score": x["score"]}
                     for x, w in zip(eligible, weights)]
    signal_frame = strategy_signals(df, cfg, asset=asset)
    row = signal_frame.iloc[-1]
    signals = {name: float(row.get(name, 0.0) or 0.0) for name in STRATEGIES}
    if blend:
        composite = sum(float(x["weight"]) * signals[x["strategy"]] for x in blend)
    else:
        composite = signals.get(chosen, 0.0)
    if not np.isfinite(composite):
        composite = 0.0
    return {
        "status": "OK", "action": action, "strategy": chosen, "regime": current_regime,
        "regime_stable_bars": stable_bars, "score": float(best["score"]),
        "signal": float(composite), "strategy_signals": signals, "ranked": ranked,
        "blend": blend, "selection_history_bars": int(len(history)),
        "policy": {"switch_min_advantage": float(switch_min_advantage),
                   "min_regime_bars": int(min_regime_bars), "min_trades": int(min_trades),
                   "online_weight": float(online_weight), "blend_top_n": int(blend_top_n),
                   "cooldown_active": bool(cooldown_active)},
    }


def router_walk_forward_backtest(df: pd.DataFrame, cfg: StrategyConfig | None = None, *,
                                 asset: str = "crypto", costs_bps: float = 7.5,
                                 folds: int = 5, min_train: int = 800,
                                 min_trades: int = 20, switch_min_advantage: float = 0.15,
                                 min_regime_bars: int = 3) -> dict:
    """Evaluate the entire regime→strategy selection process on unseen folds.

    Each test fold chooses the strategy using only bars strictly before that fold;
    the test bars then measure the selected strategy. This is the anti-lookahead gate
    for the router itself, not merely for the individual strategies.
    """
    splits = purged_walk_forward_splits(len(df), folds=folds, min_train=min_train, purge=1, embargo=1)
    if not splits:
        return {"status": "INSUFFICIENT_DATA", "folds": []}
    signals = strategy_signals(df, cfg or StrategyConfig(), asset=asset)
    regimes = classify_regime(df, asset=asset)
    rows = []
    all_net = []
    for fold in splits:
        train = df.iloc[:fold.test_start]
        if len(train) < min_train:
            continue
        perf = regime_conditioned_strategy_performance(train, cfg, costs_bps=costs_bps, asset=asset)
        chosen_by_regime = {}
        for regime in REGIMES:
            ranked = []
            for name in STRATEGIES:
                m = perf.get(name, {}).get(regime, {})
                ranked.append((name, _score_metrics(m, min_trades=min_trades)))
            ranked.sort(key=lambda x: x[1], reverse=True)
            chosen_by_regime[regime] = ranked[0][0] if ranked else "ensemble"
        test = df.iloc[fold.test_start:fold.test_end]
        test_regimes = regimes.iloc[fold.test_start:fold.test_end]
        test_ret = test["close"].pct_change().fillna(0.0)
        selected = []
        for idx in test.index:
            regime = str(test_regimes.loc[idx])
            selected.append(chosen_by_regime.get(regime, "ensemble"))
        selected_series = pd.Series(selected, index=test.index)
        raw = pd.Series(0.0, index=test.index)
        for name in STRATEGIES:
            mask = selected_series == name
            if mask.any():
                raw.loc[mask] = signals.loc[test.index, name].loc[mask]
        pos = raw.shift(1).fillna(0.0)
        turnover = pos.diff().abs().fillna(pos.abs())
        net = pos * test_ret - turnover * costs_bps / 10000.0
        all_net.append(net)
        rows.append({"test_start": test.index[0].isoformat(), "test_end": test.index[-1].isoformat(),
                     "bars": int(len(test)), "strategies_used": selected_series.value_counts().to_dict(),
                     "total_return": float((1.0 + net).prod() - 1.0)})
    joined = pd.concat(all_net) if all_net else pd.Series(dtype=float)
    m = _metrics(joined)
    m.update({"status": "OK", "folds": rows, "router": "REGIME_CONDITIONED_WALK_FORWARD"})
    return m


def policy_walk_forward_backtest(
    df: pd.DataFrame, cfg: StrategyConfig | None = None, *, asset: str = "crypto",
    costs_bps: float = 7.5, folds: int = 5, min_train: int = 800, min_trades: int = 20,
    switch_min_advantage: float = 0.15, min_regime_bars: int = 3,
    online_weight: float = 0.25, cooldown_bars: int = 6, blend_enabled: bool = True,
    blend_top_n: int = 3, decision_stride: int = 4,
) -> dict:
    """Walk-forward validate the adaptive router policy, including feedback and switching.

    This is intentionally a research simulation. Each test-bar reward becomes available
    only after that bar, so later selections may use it while earlier selections cannot.
    The simulator mirrors the live router's hold/switch/blend/abstain logic closely enough
    to test the policy as a whole rather than only ranking component strategies.
    """
    cfg = cfg or StrategyConfig()
    splits = purged_walk_forward_splits(len(df), folds=folds, min_train=min_train, purge=1, embargo=1)
    if not splits:
        return {"status": "INSUFFICIENT_DATA", "folds": []}
    signals = strategy_signals(df, cfg, asset=asset)
    regimes = classify_regime(df, asset=asset)
    fold_rows = []
    aggregate: list[float] = []

    for fold in splits:
        current_strategy = None
        last_switch_bar = -10**9
        observed = []
        prev_pos = 0.0
        net_rows = []
        test_start, test_end = fold.test_start, fold.test_end
        if test_end - test_start < 2:
            continue
        stride = max(1, int(decision_stride))
        decision_points = list(range(test_start, max(test_start + 1, test_end - 1), stride))
        for i in decision_points:
            history = df.iloc[: i + 1]
            current_regime = str(regimes.iloc[i])
            cooldown_active = (i - last_switch_bar) < int(max(0, cooldown_bars))
            online = online_strategy_scores(
                observed, current_regime=current_regime, timeframe=None,
                half_life_days=14.0, min_observations=10,
            )
            decision = select_strategy(
                history, cfg, asset=asset, current_strategy=current_strategy,
                cooldown_active=cooldown_active, min_regime_bars=min_regime_bars,
                switch_min_advantage=switch_min_advantage, min_trades=min_trades,
                costs_bps=costs_bps, online_scores=online, online_weight=online_weight,
                blend_enabled=blend_enabled, blend_top_n=blend_top_n,
            )
            if decision.get("status") != "OK" or decision.get("strategy") in {None, "none"}:
                target_pos = 0.0
            else:
                signal = float(decision.get("signal", 0.0))
                vol = float(signals.iloc[i].get("realized_vol") or 0.0)
                if not np.isfinite(vol) or vol <= 0 or abs(signal) < cfg.signal_threshold:
                    target_pos = 0.0
                else:
                    lev = min(cfg.max_leverage, cfg.target_vol_annual / vol)
                    target_pos = float(np.clip(signal * lev, -cfg.max_leverage, cfg.max_leverage))
                if decision.get("action") == "SWITCH":
                    last_switch_bar = i
                current_strategy = str(decision.get("strategy") or current_strategy or "") or None

            next_i = min(i + stride, test_end - 1)
            if next_i <= i:
                continue
            next_ret = float(df["close"].iloc[next_i] / df["close"].iloc[i] - 1.0)
            turnover = abs(target_pos - prev_pos)
            net = target_pos * next_ret - turnover * float(costs_bps) / 10000.0
            net_rows.append(net)
            if target_pos != 0.0:
                reward_bps = float(np.sign(target_pos) * next_ret * 10000.0 - float(costs_bps) * (1.0 if prev_pos == 0.0 else 0.5))
                observed.append({
                    "strategy": str(current_strategy or decision.get("strategy") or "ensemble"),
                    "regime": current_regime,
                    "net_return_bps": reward_bps,
                    "created_at": df.index[i + 1].to_pydatetime(),
                })
            prev_pos = target_pos

        fold_index = [df.index[min(i + stride, test_end - 1)] for i in decision_points if min(i + stride, test_end - 1) > i]
        fold_net = pd.Series(net_rows, index=fold_index)
        aggregate.extend(net_rows)
        fm = _metrics(fold_net)
        fm.update({
            "test_start": df.index[test_start].isoformat(),
            "test_end": df.index[test_end - 1].isoformat(),
        })
        fold_rows.append(fm)

    joined = pd.Series(aggregate, dtype=float)
    overall = _metrics(joined)
    positive_ratio = (sum(float(x.get("total_return", 0.0)) > 0 for x in fold_rows) / len(fold_rows)) if fold_rows else 0.0
    overall.update({
        "status": "OK" if fold_rows else "INSUFFICIENT_DATA",
        "folds": fold_rows,
        "positive_fold_ratio": positive_ratio,
        "router": "FULL_ADAPTIVE_POLICY_WALK_FORWARD",
        "includes": ["regime", "online_outcome_feedback", "switch_hysteresis", "blending", "abstention"],
        "decision_stride_bars": int(max(1, decision_stride)),
    })
    return overall


def strategy_trade_plan(df: pd.DataFrame, selected_strategy: str, *, signal: float,
                        atr_multiplier_stop: float = 1.5, reward_r: float = 2.5,
                        min_reward_risk: float = 2.0, cfg: StrategyConfig | None = None,
                        asset: str = "crypto") -> dict | None:
    """Create a strategy-specific direction/levels packet.

    Risk sizing remains outside this function. This function never bypasses the
    execution risk governor.
    """
    s = strategy_signals(df, cfg or StrategyConfig(), asset=asset)
    row = s.iloc[-1]
    price = float(df.close.iloc[-1])
    atr = float(row.get("atr") or 0.0)
    if not np.isfinite(price) or not np.isfinite(atr) or atr <= 0:
        return None
    side = "buy" if signal > 0.20 else ("sell" if signal < -0.20 else "flat")
    if side == "flat":
        return None
    if selected_strategy == "breakout":
        entry = price + 0.10 * atr if side == "buy" else price - 0.10 * atr
        prior_high = float(s.iloc[-1].get("breakout_high") or price)
        prior_low = float(s.iloc[-1].get("breakout_low") or price)
        stop = min(prior_low, price - atr_multiplier_stop * atr) if side == "buy" else max(prior_high, price + atr_multiplier_stop * atr)
    elif selected_strategy == "mean_reversion":
        mean = float(df.close.rolling(20).mean().iloc[-1])
        if side == "buy" and price >= mean:
            return None
        if side == "sell" and price <= mean:
            return None
        entry = price
        stop = price - atr_multiplier_stop * atr if side == "buy" else price + atr_multiplier_stop * atr
    else:
        entry = price
        stop = price - atr_multiplier_stop * atr if side == "buy" else price + atr_multiplier_stop * atr
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + reward_r * risk if side == "buy" else entry - reward_r * risk
    rr = abs(target - entry) / risk
    if rr < min_reward_risk:
        return None
    return {"side": side, "entry_price": float(entry), "stop_loss_price": float(stop),
            "take_profit_price": float(target), "reward_risk": float(rr), "atr": float(atr),
            "strategy": selected_strategy}
