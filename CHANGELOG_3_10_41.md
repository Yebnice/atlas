# AtlasRisk 3.10.41 — Unified Adaptive Strategy Router

## Purpose
This release closes the adaptive-learning loop identified in the 3.10.40 review.
The existing LightGBM model remains the trade-level confirmation layer; a new regime-aware
strategy router sits above it and below the deterministic safety/risk controls.

## Implemented
- Per-strategy, per-regime historical performance instead of a single global strategy ranking.
- Current-regime detection on completed bars only.
- Unified strategy router for trend, momentum, breakout, mean reversion and ensemble signals.
- Automatic strategy HOLD/SWITCH/ABSTAIN behavior.
- Strategy-switch hysteresis with a minimum score advantage and cooldown period.
- Optional signal-weighted mixture of the top validated strategies; this is signal blending,
  not permission to bypass portfolio/risk sizing.
- Router-level walk-forward validation using only historical data before each test fold.
- Live mode fail-closed when router OOS validation does not meet its configured evidence gate.
- Actual observed strategy outcomes stored separately from historical backtest evidence.
- Recency-weighted online outcome feedback, scoped by customer + asset + symbol.
- Strategy attribution is attached to the position that opened the exposure, not merely the closing order.
- Adaptive bot persists active strategy, active regime, switch timestamp/count and selection evidence,
  so hysteresis survives no-trade cycles.
- Explicit strategy-candidate bots do not get silently overridden by the autonomous strategy router.
- Existing LightGBM OOS promotion, AI safety veto, protective stops, customer risk limits and
  execution risk governor remain authoritative.

## Database
- Migration `0034_adaptive_strategy_router`.
- `adaptive_trading_bots`: active strategy/regime, switch state and selection evidence.
- `positions`: strategy, entry regime and entry trade ID.
- New `strategy_outcomes` table for observed trade outcomes.

## Safety model
The router cannot authorize custody, withdrawals, position size or live execution by itself.
Every selected signal still passes through the existing execution/risk controls.

This release does not claim any strategy is guaranteed to work or that adaptive switching guarantees profit.
The router is designed to select among strategies only when historical/OOS evidence supports doing so;
otherwise it can hold or abstain.
