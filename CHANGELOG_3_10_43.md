# AtlasRisk 3.10.43 — Live Execution Control Plane Hardening

## Implemented from the 3.10.42 deep architectural review

### P0 execution safety
- Added a deny-by-default `LiveExecutionGate` immediately before every supported live crypto order submission.
- Disabled customer and admin Deriv live execution until it uses the unified order/ledger/reconciliation path.
- Disabled Binance triangular-arbitrage live execution until its multi-leg lifecycle is represented in the durable order path.
- Added PostgreSQL-backed `live_execution_lease` with fencing tokens to serialize live submissions across worker instances.
- Added durable `order_commands` records with idempotency and client-order uniqueness.
- Made customer cash reservation and initial live order command creation atomic in the same database transaction.
- Added final-gate rollback so a last-moment live authorization/risk failure releases newly reserved customer capital.
- Re-checked customer profile, account, subscription/plan, platform live state and strategy entitlement before each persisted DCA/TWAP live slice.
- Executor progress now advances using confirmed broker `filled` quantity, not requested slice quantity.

### Protective controls
- Live crypto entries now verify that a required protective stop is visible after execution.
- Verification accepts both standalone stop orders and exchanges that report the stop as an attached `stopLoss` object.
- Missing/failed protective-stop verification halts live trading and opens a critical incident.
- Emergency stop now sweeps verified customer Binance accounts as well as the platform account and records customer-specific cancellation failures as critical incidents.

### Production gates
- `/readyz` now requires the persisted execution-fencing control plane rather than relying on Cloud Run's single-worker assumption.
- Production live payouts require `EXTERNAL_CUSTODY_SIGNER_REQUIRED=true`.
- OANDA remains demo/practice only.

### Database integrity
- `order_commands.trade_id` references `trades.id`.
- `order_commands.customer_id` references `customer_profiles.id`.
- Migration head advanced to `0036_execution_control_plane`.

## Verification performed in this build

- Python compileall: PASS.
- Targeted release/execution regression suite after release-identity correction: 43 passed.
- 3.10.43 control-plane tests: 12 passed (included in the targeted total).
- Full pytest suite remains environment-blocked here because `aiosqlite==0.22.1` is not installed and package-network access is unavailable; this is not reported as a passing full-suite result.
- Static migration graph check: 36 revisions discovered; no missing `down_revision` references.
- Real PostgreSQL migration/concurrency certification was not executed in this container because no PostgreSQL service was available.
- `bandit` and `pip-audit` were not installed in the container, so those external dependency/security gates remain to be run in CI/staging.

## GitHub
No GitHub push or repository mutation was performed.

## Post-audit correction

- Corrected runtime/application version from 3.10.42 to 3.10.43 in `app/config.py` and `app/__init__.py`.
- Corrected Android `versionCode` from 1042 to 1043 and `versionName` to 3.10.43.
- Updated stale historical regression assertions that were still checking for 3.10.39.
- Kept `REPLAY_VERSION = 3.10.42-replay-v1` unchanged because it identifies the replay data/schema version, not the application release.
