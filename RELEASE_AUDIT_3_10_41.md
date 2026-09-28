# AtlasRisk 3.10.41 Release Audit

## Scope
Close the six adaptive-learning gaps identified during the 3.10.40 forensic review:
regime-conditioned strategy evidence, automatic live switching, observed-outcome feedback,
signal mixture, switching hysteresis/cooldown, and one unified adaptive strategy router.

## Confirmed code changes
- Added `app/strategy_router.py`.
- Router classifies completed-bar regimes: `TREND_UP`, `TREND_DOWN`, `RANGE`, `HIGH_VOL`, `TRANSITION`.
- Router evaluates `trend`, `momentum`, `breakout`, `mean_reversion`, and `ensemble` separately inside each regime.
- Router selects a primary strategy from historical evidence and can blend top strategies into one signal.
- Router holds during cooldown or when a challenger does not exceed the current strategy by the configured advantage.
- Router can abstain during unstable transitions.
- Router performs a dedicated walk-forward validation of the selection process itself.
- Live customer adaptive trading fails closed if the router's OOS validation gate is not passed.
- Actual realized outcomes are stored in `strategy_outcomes` and used as a bounded, recency-weighted online adjustment.
- Attribution is tied to the strategy/regime that opened the position via `Position.strategy`, `Position.entry_regime`, and `Position.entry_trade_id`.
- Adaptive bot persists selection state so switching cooldown is not lost when a cycle produces no trade.
- Explicit strategy candidates are excluded from autonomous strategy switching.
- Existing deterministic risk and execution controls remain authoritative.

## Verification performed
- Adaptive strategy-router test suite: `7 passed`.
- Alembic graph: `34` revisions, `34` unique, `0` missing down-revision references.
- Alembic head: `0034_adaptive_strategy_router`.
- Python compilation: passed for `app` and `alembic`.

## Full-suite limitation
A complete pytest run could not be completed in the current sandbox because the environment lacks `aiosqlite`, which is required by the project's async SQLite test engine. This is explicitly not treated as a pass/fail result for the full suite.

Fresh PostgreSQL migration, PostgreSQL concurrency, Redis/worker failover, external exchange failure drills,
Cloud Logging retention, and live venue end-to-end tests still require the real verification environment.
