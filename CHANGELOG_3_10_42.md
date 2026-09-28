# AtlasRisk 3.10.42 — Trade Memory & Counterfactual Replay

## Purpose
Build the next layer of adaptive intelligence without giving the learning system execution authority.

## Added
- `TradeLearningEpisode` persistent post-trade memory anchored to the position-opening trade.
- `TradeReplayResult` counterfactual strategy replay for every completed learning episode.
- Post-trade market-flow analysis: MAE, MFE, regime at entry/exit, regime transitions and holding bars.
- Separate gross P&L, total fees, net P&L and net return attribution for observed strategy outcomes.
- Regime-aware online strategy scores using completed net outcomes with conservative shrinkage toward broader experience.
- Full adaptive-policy walk-forward validation including regime detection, online feedback, switching hysteresis, blending and abstention.
- Background worker for post-trade replay and learning-memory processing.
- Admin learning-memory endpoints for audit/review of episodes and counterfactuals.
- OANDA remains practice/demo-only; replay is research-only and cannot enable live OANDA trading.

## Safety rules
- A real trade is never "rolled back" in the market. Atlas replays the decision window after the fact.
- Future bars are used only in post-trade learning, never in the live decision snapshot.
- Counterfactual replay is research evidence, not an order instruction.
- Risk, live authorization, custody and execution controls remain above the learning layer.

## Verification
- Pure replay unit test passes.
- Adaptive router regression suite updated for regime-aware net-outcome feedback.
- Full runtime/PostgreSQL suite still requires the external verification environment because the sandbox lacks `aiosqlite` and a live PostgreSQL service.
