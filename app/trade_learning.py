from __future__ import annotations

"""Trade Memory, Replay and Counterfactual Learning for AtlasRisk.

A real market trade is never "rolled back". Instead, every completed adaptive
position becomes a post-trade learning episode. The episode records what the bot
knew at decision time and separately stores future-only facts such as realized P&L,
MAE/MFE, regime path and counterfactual strategy replays.

The learning side is deliberately separated from the live decision path so that
future information can never become an input to a historical/live decision.
"""

import asyncio
import json
from datetime import datetime, timezone
from math import isfinite
from typing import Any, TYPE_CHECKING

import numpy as np
import pandas as pd
from sqlalchemy import select

if TYPE_CHECKING:
    from .db import TradeLearningEpisode
from .data import fetch_crypto, fetch_forex, fetch_forex_oanda
from .strategy_engine import StrategyConfig, strategy_signals
from .strategy_router import STRATEGIES, classify_regime

REPLAY_VERSION = "3.10.42-replay-v1"


def _parse_dt(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts
    except Exception:
        return None


def _nearest_index(df: pd.DataFrame, timestamp: Any, *, side: str = "nearest") -> int | None:
    ts = _parse_dt(timestamp)
    if ts is None or df.empty:
        return None
    idx = pd.DatetimeIndex(df.index)
    pos = idx.searchsorted(ts)
    if side == "left":
        return int(max(0, min(len(idx) - 1, pos - 1)))
    if pos <= 0:
        return 0
    if pos >= len(idx):
        return len(idx) - 1
    before = pos - 1
    after = pos
    if abs((idx[after] - ts).total_seconds()) < abs((ts - idx[before]).total_seconds()):
        return int(after)
    return int(before)


def _directional_bps(side: str, entry: float, exit_price: float) -> float:
    if entry <= 0 or exit_price <= 0:
        return 0.0
    raw = (exit_price / entry - 1.0) if str(side).lower() == "buy" else (entry / exit_price - 1.0)
    return float(raw * 10000.0)


def replay_trade_episode(
    df: pd.DataFrame,
    episode: "TradeLearningEpisode",
    *,
    cfg: StrategyConfig | None = None,
    costs_bps: float = 7.5,
) -> dict[str, Any]:
    """Replay one completed episode without changing the live decision state.

    Two complementary measures are produced:
      * entry_decision_bps: what each strategy's signal at the actual entry would
        have earned if it had taken the same exit timestamp;
      * policy_window_bps: the strategy's own signal policy over the same future
        window, evaluated only after the historical entry point.

    These are counterfactual research measurements, not executable orders.
    """
    cfg = cfg or StrategyConfig()
    entry_idx = _nearest_index(df, episode.entry_at, side="nearest")
    exit_idx = _nearest_index(df, episode.exit_at, side="nearest")
    if entry_idx is None or exit_idx is None or exit_idx <= entry_idx:
        raise ValueError("Replay requires a completed episode with valid entry and exit timestamps")

    # Never use bars prior to entry for the outcome window itself. Indicators may
    # legitimately use earlier history through rolling windows.
    entry_row = df.iloc[entry_idx]
    exit_row = df.iloc[exit_idx]
    entry_price = float(episode.entry_price or entry_row["close"])
    exit_price = float(episode.exit_price or exit_row["close"])
    if not all(isfinite(x) and x > 0 for x in (entry_price, exit_price)):
        raise ValueError("Replay prices must be positive and finite")

    window = df.iloc[entry_idx : exit_idx + 1].copy()
    signals = strategy_signals(df.iloc[: exit_idx + 1], cfg, asset=episode.asset or "crypto")
    regimes = classify_regime(df.iloc[: exit_idx + 1], asset=episode.asset or "crypto")
    entry_regime = str(regimes.iloc[entry_idx]) if len(regimes) > entry_idx else "UNKNOWN"
    exit_regime = str(regimes.iloc[exit_idx]) if len(regimes) > exit_idx else "UNKNOWN"
    regime_path = [str(x) for x in regimes.iloc[entry_idx : exit_idx + 1].tolist()]
    transitions = 0
    for a, b in zip(regime_path, regime_path[1:]):
        if a != b:
            transitions += 1

    if str(episode.side).lower() == "buy":
        mfe = (float(window["high"].max()) / entry_price - 1.0) * 10000.0
        mae = (float(window["low"].min()) / entry_price - 1.0) * 10000.0
    else:
        mfe = (entry_price / float(window["low"].min()) - 1.0) * 10000.0
        mae = (entry_price / float(window["high"].max()) - 1.0) * 10000.0

    notional = abs(float(episode.entry_quantity or 0.0)) * entry_price
    counterfactuals: list[dict[str, Any]] = []
    for name in STRATEGIES:
        signal_value = float(signals.iloc[entry_idx].get(name, 0.0) or 0.0)
        if signal_value > cfg.signal_threshold:
            cf_side = "buy"
        elif signal_value < -cfg.signal_threshold:
            cf_side = "sell"
        else:
            cf_side = "flat"
        entry_bps = 0.0 if cf_side == "flat" else _directional_bps(cf_side, entry_price, exit_price) - 2.0 * float(costs_bps)

        # Same future window, strategy policy held from one bar after entry. This
        # prevents the entry bar's close from becoming an execution input.
        subset = df.iloc[entry_idx : exit_idx + 1]
        strat_sig = signals[name].iloc[entry_idx : exit_idx + 1].fillna(0.0)
        vol = signals["realized_vol"].iloc[entry_idx : exit_idx + 1]
        lev = (cfg.target_vol_annual / vol.replace(0, np.nan)).clip(upper=cfg.max_leverage)
        pos = (strat_sig * lev).clip(-cfg.max_leverage, cfg.max_leverage)
        pos = pos.where(strat_sig.abs() >= cfg.signal_threshold, 0.0).shift(1).fillna(0.0)
        returns = subset["close"].pct_change().fillna(0.0)
        turnover = pos.diff().abs().fillna(pos.abs())
        net = pos * returns - turnover * float(costs_bps) / 10000.0
        policy_bps = float(((1.0 + net).prod() - 1.0) * 10000.0)
        counterfactuals.append({
            "strategy": name,
            "entry_signal": signal_value,
            "entry_side": cf_side,
            "entry_decision_return_bps": float(entry_bps),
            "policy_window_return_bps": policy_bps,
            "confidence": "HIGH" if len(window) >= 5 and df.index.is_monotonic_increasing else "MEDIUM",
            "comparison_scope": "same_entry_and_exit_window; strategy_policy_replay",
        })

    actual_directional_bps = _directional_bps(episode.side, entry_price, exit_price)
    actual_net_bps = float(episode.net_pnl / notional * 10000.0) if notional > 0 else actual_directional_bps
    best = max(counterfactuals, key=lambda x: float(x.get("policy_window_return_bps", -1e18)))
    chosen = next((x for x in counterfactuals if x["strategy"] == (episode.strategy or "")), None)
    chosen_policy_bps = float((chosen or {}).get("policy_window_return_bps", actual_net_bps))

    return {
        "replay_version": REPLAY_VERSION,
        "entry_index": int(entry_idx),
        "exit_index": int(exit_idx),
        "bars_held": int(len(window) - 1),
        "entry_regime": entry_regime,
        "exit_regime": exit_regime,
        "regime_transitions": int(transitions),
        "actual_directional_return_bps": float(actual_directional_bps),
        "actual_net_return_bps": float(actual_net_bps),
        "mfe_bps": float(mfe),
        "mae_bps": float(mae),
        "chosen_strategy_policy_bps": chosen_policy_bps,
        "best_counterfactual_strategy": best["strategy"],
        "best_counterfactual_policy_bps": float(best["policy_window_return_bps"]),
        "selection_regret_bps": float(best["policy_window_return_bps"] - chosen_policy_bps),
        "counterfactuals": counterfactuals,
        "market_flow": {
            "entry_regime": entry_regime,
            "exit_regime": exit_regime,
            "regime_path": regime_path[-24:],
            "regime_transitions": transitions,
            "bars": len(window) - 1,
        },
        "future_data_used_only_for_post_trade_learning": True,
    }


def _fetch_learning_data(episode: TradeLearningEpisode, *, days: int = 365) -> pd.DataFrame:
    asset = str(episode.asset or "crypto").lower()
    if asset == "crypto":
        return fetch_crypto(
            symbol=episode.symbol,
            exchange=episode.exchange or "bybit",
            timeframe=episode.timeframe or "1h",
            days=days,
            closed_only=True,
        )
    if asset == "forex":
        if str(episode.exchange or "").lower() == "oanda":
            return fetch_forex_oanda(symbol=episode.symbol, timeframe=episode.timeframe or "1h", days=days)
        return fetch_forex(symbol=episode.symbol, timeframe=episode.timeframe or "1h", days=days)
    if asset == "commodity":
        return fetch_forex(symbol=episode.symbol, timeframe=episode.timeframe or "1h", days=days)
    raise ValueError(f"Unsupported replay asset: {asset}")


async def process_trade_learning_episodes(*, limit: int = 10, lookback_days: int = 365) -> dict[str, Any]:
    """Process completed episodes and persist market-memory/counterfactual results."""
    from .db import SessionLocal, TradeLearningEpisode, TradeReplayResult
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(TradeLearningEpisode)
            .where(TradeLearningEpisode.status == "COMPLETED")
            .where(TradeLearningEpisode.replay_status.in_(["PENDING", "ERROR"]))
            .order_by(TradeLearningEpisode.exit_at.asc())
            .limit(max(1, int(limit)))
        )).scalars().all()

    processed = 0
    failed = 0
    skipped = 0
    for episode in rows:
        try:
            df = await asyncio.to_thread(_fetch_learning_data, episode, days=lookback_days)
            result = await asyncio.to_thread(replay_trade_episode, df, episode, costs_bps=7.5)
            async with SessionLocal() as db:
                ep = await db.get(TradeLearningEpisode, episode.id, with_for_update=True)
                if not ep:
                    continue
                ep.replay_status = "COMPLETE"
                ep.replay_version = REPLAY_VERSION
                ep.bars_held = int(result["bars_held"])
                ep.mfe_bps = float(result["mfe_bps"])
                ep.mae_bps = float(result["mae_bps"])
                ep.market_flow_json = json.dumps(result.get("market_flow", {}), default=str)
                ep.learning_memory_json = json.dumps(result, default=str)
                for cf in result.get("counterfactuals", []):
                    existing = (await db.execute(
                        select(TradeReplayResult).where(
                            TradeReplayResult.episode_id == ep.id,
                            TradeReplayResult.strategy == str(cf.get("strategy")),
                        )
                    )).scalar_one_or_none()
                    if existing is None:
                        existing = TradeReplayResult(episode_id=ep.id, strategy=str(cf.get("strategy")))
                        db.add(existing)
                    existing.entry_signal = float(cf.get("entry_signal") or 0.0)
                    existing.entry_side = str(cf.get("entry_side") or "flat")
                    existing.entry_decision_return_bps = float(cf.get("entry_decision_return_bps") or 0.0)
                    existing.policy_window_return_bps = float(cf.get("policy_window_return_bps") or 0.0)
                    existing.confidence = str(cf.get("confidence") or "LOW")
                    existing.comparison_scope = str(cf.get("comparison_scope") or "")
                    existing.metadata_json = json.dumps(cf, default=str)
                ep.updated_at = datetime.now(timezone.utc)
                await db.commit()
            processed += 1
        except ValueError as exc:
            async with SessionLocal() as db:
                ep = await db.get(TradeLearningEpisode, episode.id, with_for_update=True)
                if ep:
                    ep.replay_status = "UNSUPPORTED"
                    ep.replay_error = str(exc)
                    ep.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            skipped += 1
        except Exception as exc:
            async with SessionLocal() as db:
                ep = await db.get(TradeLearningEpisode, episode.id, with_for_update=True)
                if ep:
                    ep.replay_status = "ERROR"
                    ep.replay_error = str(exc)
                    ep.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            failed += 1
    return {"processed": processed, "failed": failed, "skipped": skipped, "selected": len(rows), "replay_version": REPLAY_VERSION}
