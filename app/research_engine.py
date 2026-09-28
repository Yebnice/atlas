from __future__ import annotations
from dataclasses import asdict
import math
import numpy as np
import pandas as pd

from .strategy_engine import StrategyConfig, strategy_signals, risk_scaled_position, strategy_backtest
from .trading_core import ai_walk_forward_backtest
from .strategy_evidence import evidence_for
from .research_validation import monte_carlo_bootstrap, parameter_plateau_score
from .config import settings
from .research_validation import (validate_ohlcv_frame, bootstrap_mean_ci,
                                  multiple_testing_sharpe_adjustment, cost_sensitivity,
                                  purged_walk_forward_splits, fixed_signal_walk_forward_oos,
                                  regime_conditioned_performance)


def _safe(x: float, default: float = 0.0) -> float:
    return float(x) if np.isfinite(x) else default


def _component_backtest(df: pd.DataFrame, component: str, cfg: StrategyConfig, taker_bps: float, slippage_bps: float, asset: str = "crypto") -> dict:
    """Cost-aware component backtest with forward-looking risk protections.

    Protections are applied using only information available at the end of the
    completed bar: volatility cap, peak drawdown halt, daily-loss halt, and a
    stop-loss cluster cooldown. This is deliberately conservative and avoids
    treating an attractive raw backtest as production evidence.
    """
    s = strategy_signals(df, cfg, asset=asset)
    raw = s[component].fillna(0.0)
    vol = s["realized_vol"]
    lev = (cfg.target_vol_annual / vol.replace(0, np.nan)).clip(upper=cfg.max_leverage)
    pos = (raw * lev).clip(-cfg.max_leverage, cfg.max_leverage).shift(1).fillna(0.0)
    ret = df["close"].pct_change().fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    costs = turnover * ((taker_bps + slippage_bps) / 10_000.0)
    net = pos * ret - costs

    equity = 1.0
    peak = 1.0
    day_start = 1.0
    current_day = None
    halted_until = -1
    loss_event_times: list[int] = []
    equity_curve = []
    protected_pos = []
    for i, value in enumerate(net.to_numpy(dtype=float)):
        ts = df.index[i]
        day = ts.date() if hasattr(ts, "date") else None
        if day != current_day:
            current_day = day
            day_start = equity
        if i <= halted_until:
            effective = 0.0
        else:
            effective = float(value)
        equity = max(0.0, equity * (1.0 + effective))
        peak = max(peak, equity)
        dd = 1.0 - (equity / peak if peak else 0.0)
        daily_loss = 1.0 - (equity / day_start if day_start else 0.0)
        protected_pos.append(0.0 if i <= halted_until else float(pos.iloc[i]))
        equity_curve.append(equity)

        # Approximate a stop-loss event from a negative active-bar return. This
        # is intentionally conservative; execution-level backtests remain the
        # authoritative place for exact stop ordering.
        if pos.iloc[i] != 0 and value < 0:
            loss_event_times.append(i)
        cutoff = i - 24
        loss_event_times = [x for x in loss_event_times if x >= cutoff]
        if (dd >= settings.strategy_drawdown_halt or daily_loss >= settings.strategy_daily_loss_halt or len(loss_event_times) >= settings.strategy_stoploss_guard_trades):
            halted_until = max(halted_until, i + settings.strategy_stoploss_guard_bars)

    protected = pd.Series(protected_pos, index=df.index)
    turnover_protected = protected.diff().abs().fillna(protected.abs())
    active = protected != 0
    ann = float(s.attrs.get("annualization_factor", 252.0))
    protected_net = protected * ret - turnover_protected * ((taker_bps + slippage_bps) / 10_000.0)
    protected_equity = (1.0 + protected_net).cumprod()
    protected_peak = protected_equity.cummax()
    protected_dd = protected_equity / protected_peak - 1.0
    std = float(protected_net.std())
    return {
        "strategy": component,
        "bars": int(len(df)),
        "validated_bars": int(s[[component, "atr", "realized_vol"]].notna().all(axis=1).sum()),
        "total_return": _safe(protected_equity.iloc[-1] - 1.0),
        "max_drawdown": _safe(protected_dd.min()),
        "sharpe": _safe(protected_net.mean() / std * math.sqrt(ann)) if std > 0 else 0.0,
        "trades": int((turnover_protected > 0).sum()),
        "hit_rate": _safe((protected_net[active] > 0).mean()) if bool(active.any()) else 0.0,
        "average_leverage": _safe(protected.abs().mean()),
        "max_leverage": _safe(protected.abs().max()),
        "transaction_cost_bps": float(taker_bps + slippage_bps),
        "annualization_factor": ann,
        "risk_protections": {
            "drawdown_halt": settings.strategy_drawdown_halt,
            "daily_loss_halt": settings.strategy_daily_loss_halt,
            "loss_event_guard": settings.strategy_stoploss_guard_trades,
            "cooldown_bars": settings.strategy_stoploss_guard_bars,
            "note": "A negative active-bar return is treated as a loss event; this is NOT an exact stop-loss fill detector.",
        },
    }


def _regime_snapshot(df: pd.DataFrame, cfg: StrategyConfig, asset: str = "crypto") -> dict:
    s = strategy_signals(df, cfg, asset=asset)
    c = df["close"].astype(float)
    fast = c.ewm(span=cfg.trend_fast, adjust=False).mean()
    slow = c.ewm(span=cfg.trend_slow, adjust=False).mean()
    trend_strength = abs(float(fast.iloc[-1] / slow.iloc[-1] - 1.0)) if len(df) else 0.0
    vol = float(s["realized_vol"].dropna().iloc[-1]) if s["realized_vol"].notna().any() else 0.0
    if trend_strength >= 0.01 and float(fast.iloc[-1]) > float(slow.iloc[-1]):
        regime = "TREND_UP"
    elif trend_strength >= 0.01 and float(fast.iloc[-1]) < float(slow.iloc[-1]):
        regime = "TREND_DOWN"
    elif vol >= 0.60:
        regime = "HIGH_VOLATILITY_RANGE"
    else:
        regime = "RANGE_OR_LOW_TREND"
    return {"regime": regime, "annualized_realized_vol": _safe(vol), "trend_strength": _safe(trend_strength)}


def _rank_for_research(rows: list[dict]) -> list[dict]:
    # This is a research ordering, not a recommendation. It rewards risk-adjusted
    # evidence while penalizing severe drawdown and insufficient observations.
    for r in rows:
        r["research_score"] = _safe(
            0.45 * r["sharpe"] + 2.0 * r["total_return"] + 0.15 * r["hit_rate"] +
            0.10 * r["trades"] / max(r["bars"], 1) - 0.60 * abs(min(r["max_drawdown"], 0.0))
        )
    return sorted(rows, key=lambda x: x["research_score"], reverse=True)


def backtest_all_strategies(df: pd.DataFrame, cfg: StrategyConfig | None = None,
                            taker_bps: float = 5.5, slippage_bps: float = 2.0,
                            include_ai: bool = True, asset: str = "crypto",
                            folds: int = 5, min_train: int = 800,
                            ai_threshold: float = 0.05) -> dict:
    cfg = cfg or StrategyConfig()
    data_quality = validate_ohlcv_frame(df)
    if not data_quality["valid"]:
        return {"research_version": "3.10.3-validation-v1", "status": "DATA_INVALID",
                "data_quality": data_quality, "strategies": [], "strategy_count": 0}
    components = ["trend", "momentum", "breakout", "mean_reversion", "ensemble"]
    results = [_component_backtest(df, c, cfg, taker_bps, slippage_bps, asset) for c in components]
    for row in results:
        row["evidence"] = evidence_for(row["strategy"])
    validation_splits = purged_walk_forward_splits(len(df), folds=folds, min_train=min_train, purge=1, embargo=1)
    ensemble_signal = strategy_signals(df, cfg, asset=asset)["ensemble"].fillna(0.0)
    gross = ensemble_signal.shift(1).fillna(0.0) * df["close"].pct_change().fillna(0.0)
    turnover = ensemble_signal.diff().abs().shift(1).fillna(0.0)
    sensitivity = cost_sensitivity(gross.to_numpy(), turnover.to_numpy())
    ci = bootstrap_mean_ci((gross - turnover * ((taker_bps + slippage_bps) / 10000.0)).to_numpy(), block_size=10)
    adjusted = multiple_testing_sharpe_adjustment([r.get("sharpe", 0.0) for r in results], trials=len(results))
    oos = fixed_signal_walk_forward_oos(df, ensemble_signal,
                                        costs_bps=taker_bps + slippage_bps, folds=folds, min_train=min_train)
    gross_net = ensemble_signal.shift(1).fillna(0.0) * df["close"].pct_change().fillna(0.0)
    regime_performance = regime_conditioned_performance(df, gross_net - turnover * ((taker_bps + slippage_bps) / 10000.0), asset=asset)
    per_strategy_oos = {}
    for component in components:
        component_signal = strategy_signals(df, cfg, asset=asset)[component]
        per_strategy_oos[component] = fixed_signal_walk_forward_oos(
            df, component_signal, costs_bps=taker_bps + slippage_bps, folds=folds, min_train=min_train
        )
    # Parameter-plateau check: small changes to the signal threshold should not destroy
    # the measured edge. A narrow single-point optimum is treated as fragile research.
    variants=[]
    for mult in (0.80,0.90,1.00,1.10,1.20):
        vcfg=StrategyConfig(**{**asdict(cfg), "signal_threshold": float(cfg.signal_threshold*mult)})
        vr=_component_backtest(df,"ensemble",vcfg,taker_bps,slippage_bps,asset)
        variants.append({"multiplier":mult,"sharpe":vr.get("sharpe",0.0),"total_return":vr.get("total_return",0.0),"max_drawdown":vr.get("max_drawdown",0.0)})
    robustness={"monte_carlo":monte_carlo_bootstrap((gross - turnover * ((taker_bps + slippage_bps) / 10000.0)).to_numpy(),trials=500),"parameter_plateau":parameter_plateau_score({"variants":variants},metric="sharpe",tolerance=0.20),"parameter_variants":variants}
    ai_result = None
    if include_ai:
        try:
            ai_result = ai_walk_forward_backtest(df, asset, folds, min_train, ai_threshold)
        except Exception as exc:
            ai_result = {"strategy": "ai_walk_forward", "status": "INSUFFICIENT_DATA", "error": str(exc)}
    ranked = _rank_for_research(results.copy())
    return {
        "research_version": "3.10.3-validation-v1",
        "data_quality": data_quality,
        "validation": {"purged_walk_forward_folds": [fold.__dict__ for fold in validation_splits],
                        "cost_sensitivity": sensitivity,
                        "bootstrap_mean_return_ci": ci,
                        "multiple_testing_sharpe_proxy": adjusted,
                        "fixed_signal_oos": oos,
                        "per_strategy_oos": per_strategy_oos,
                        "regime_conditioned_performance": regime_performance},
        "strategy_count": len(results) + (1 if ai_result else 0),
        "strategies": results,
        "research_order": [r["strategy"] for r in ranked],
        "ai_walk_forward": ai_result,
        "regime": _regime_snapshot(df, cfg, asset=asset),
        "robustness": robustness,
        "config": asdict(cfg),
    }


def paper_candidates(
    research: dict,
    min_sharpe: float | None = None,
    max_drawdown: float | None = None,
    min_trades: int | None = None,
    min_oos_total_return: float | None = None,
    min_oos_positive_fold_ratio: float | None = None,
) -> list[dict]:
    """Select paper candidates using both historical and forward-only evidence.

    In-sample metrics alone are never sufficient. The OOS gate is intentionally
    simple and transparent; it is not a guarantee of future performance.
    """
    min_sharpe = settings.adaptive_min_sharpe if min_sharpe is None else float(min_sharpe)
    max_drawdown = settings.adaptive_max_drawdown if max_drawdown is None else float(max_drawdown)
    min_trades = settings.adaptive_min_trades if min_trades is None else int(min_trades)
    min_oos_total_return = settings.research_min_oos_total_return if min_oos_total_return is None else float(min_oos_total_return)
    min_oos_positive_fold_ratio = settings.research_min_oos_positive_fold_ratio if min_oos_positive_fold_ratio is None else float(min_oos_positive_fold_ratio)
    candidates = []
    oos_all = research.get("validation", {}).get("per_strategy_oos", {})
    for row in research.get("strategies", []):
        name = row.get("strategy")
        oos = oos_all.get(name, {})
        folds = oos.get("folds", []) or []
        positive_ratio = (sum(1 for f in folds if float(f.get("total_return", 0.0)) > 0) / len(folds)) if folds else 0.0
        if (row.get("sharpe", 0.0) >= min_sharpe and
                row.get("max_drawdown", 0.0) >= max_drawdown and
                row.get("trades", 0) >= min_trades and
                row.get("total_return", 0.0) > 0 and
                oos.get("status") == "OK" and
                float(oos.get("oos_total_return", -1.0)) >= min_oos_total_return and
                positive_ratio >= min_oos_positive_fold_ratio):
            candidates.append({"strategy": name, "reason": "in_sample_and_forward_gate_passed",
                               "metrics": row, "oos": oos,
                               "oos_positive_fold_ratio": positive_ratio})
    return candidates


def live_strategy_signals(df: pd.DataFrame, strategies: list[str], cfg: StrategyConfig | None = None, asset: str = "crypto") -> list[dict]:
    cfg = cfg or StrategyConfig()
    s = strategy_signals(df, cfg, asset=asset)
    latest = s.iloc[-1]
    price = float(df["close"].iloc[-1])
    output = []
    for name in strategies:
        if name not in {"trend", "momentum", "breakout", "mean_reversion", "ensemble"}:
            continue
        raw = float(latest[name]) if np.isfinite(latest[name]) else 0.0
        vol = float(latest["realized_vol"]) if np.isfinite(latest["realized_vol"]) else 0.0
        position = risk_scaled_position(raw, vol, cfg) if abs(raw) >= cfg.signal_threshold else 0.0
        output.append({
            "strategy": name, "timestamp": s.index[-1].isoformat(), "price": price,
            "signal": raw, "position_leverage": position,
            "side": "buy" if position > 0 else ("sell" if position < 0 else "flat"),
            "realized_vol_annual": vol, "mode": "PAPER_SHADOW_ONLY"
        })
    return output


def ai_market_review(research: dict, live_signal: dict | None = None) -> dict:
    rows = research.get("strategies", [])
    regime = research.get("regime", {})
    if not rows:
        return {"status": "NO_DATA", "summary": "No strategy research results are available."}
    best = max(rows, key=lambda r: r.get("research_score", -1e9))
    profitable = [r for r in rows if r.get("total_return", 0) > 0 and r.get("sharpe", 0) > 0]
    drawdown_warnings = [r["strategy"] for r in rows if r.get("max_drawdown", 0) < -0.25]
    summary = (
        f"Current regime classified as {regime.get('regime', 'UNKNOWN')}. "
        f"The research set contains {len(rows)} rule-based strategy variants. "
        f"{len(profitable)} showed positive return and positive Sharpe in this historical test."
    )
    observations = [
        f"Highest research score in this run: {best['strategy']} ({best['research_score']:.3f}).",
        f"Current annualized realized volatility: {regime.get('annualized_realized_vol', 0):.3f}.",
    ]
    if drawdown_warnings:
        observations.append("Large historical drawdowns detected in: " + ", ".join(drawdown_warnings) + ".")
    if live_signal:
        observations.append(
            f"Live ensemble signal is {live_signal.get('side', 'unknown')} with score "
            f"{float(live_signal.get('ensemble_score', 0)):.3f}; this is context, not a trade recommendation."
        )
    return {
        "status": "REVIEW_READY",
        "summary": summary,
        "observations": observations,
        "regime": regime,
        "research_order": research.get("research_order", []),
        "paper_candidates": paper_candidates(research),
        "limitations": [
            "Historical backtests do not guarantee future performance.",
            "Walk-forward validation reduces but does not eliminate overfitting.",
            "Live promotion should require paper/shadow evidence and risk gates.",
        ],
    }
