# AtlasRisk 3.10.42 Release Audit

## Scope
Trade memory, counterfactual replay, market-flow attribution, net outcome learning, and policy-level validation of the complete adaptive router.

## Confirmed implementation
- Every new Trade can create a post-trade learning episode containing the decision-time strategy/regime/model snapshot.
- A position lifecycle becomes `COMPLETED` only after the position quantity returns to zero; reversals close the old episode and initialize the new lifecycle.
- Strategy outcomes now store `net_pnl` and `net_return_bps` in addition to gross realized P&L and fee fields.
- Online strategy scores prefer current-regime net outcomes and shrink toward broader experience when regime samples are sparse.
- Replay uses only completed episodes and future bars after the actual entry point.
- Replay measures entry-decision counterfactuals, strategy-policy performance over the same future window, MAE, MFE and regime transitions.
- Replay is explicitly post-trade research and never creates a live order.
- A worker loop processes pending completed episodes.
- The admin learning endpoints are read-only and role protected.
- Policy walk-forward validation includes regime, online feedback, hysteresis, blending and abstention, rather than only selecting the historically best strategy per regime.

## Important limitation
The policy validator uses a configurable decision stride to keep the research workload bounded. It is a validation simulation, not proof of future profitability. Live deployment still requires paper/shadow evidence and the external PostgreSQL/exchange failure gates.

## Test status
- `test_trade_learning_3_10_42.py`: 1 passed.
- Existing adaptive-router subset excluding the intentionally compute-heavy policy test: 8 passed.
- A smaller policy walk-forward smoke test completed successfully with `FULL_ADAPTIVE_POLICY_WALK_FORWARD` and two folds.
- Full suite remains environment-blocked by the sandbox's missing `aiosqlite`; no claim of complete production certification is made.
