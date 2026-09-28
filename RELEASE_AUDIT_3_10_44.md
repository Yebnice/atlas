# AtlasRisk 3.10.44 Second-Pass Root-Bug Audit

## Scope
This patch release follows an adversarial second review of AtlasRisk 3.10.43, including endpoint reachability, customer isolation, execution idempotency, reserve accounting, worker lease behavior, and feature dead ends.

## Root defects corrected
- Customer position isolation in platform reconciliation.
- Orphan `PENDING` trades when customer capital reservation races and fails.
- DCA/TWAP executor recovery from duplicate commands now returns persisted fill state.
- OANDA demo enable endpoint no longer accesses a broker after closing it.
- Customer Deriv execution endpoint requires customer AAL2 before its fail-closed response.
- FX execution research endpoints require admin authentication/role.
- Customer live execution IDs now support explicit request/bot/executor scope to avoid cross-executor idempotency collisions.
- Customer execution reserves are persisted explicitly and include a configurable slippage buffer. Partial orders retain their reserve until terminal state.
- Reserve deficits above the stored collateral open a critical reconciliation incident rather than silently under-collateralizing the customer ledger.
- DCA/Grid START endpoints now fail closed because no live execution controller exists for those product models; they can only be configured as paper features.
- Alert API no longer claims an automatic evaluator that is not implemented.
- Redis adaptive/executor worker leases are refreshed immediately before submit; a worker that lost its lease cannot submit a trade.
- Deriv customer UI/API now explicitly describe the connection/preflight flow as verification-only; live trading remains disabled.
- Live customer bot/executor activation now runs the same final server-side authority preflight used at order submission, preventing automation from entering a RUNNING/ARMED dead end when the verified Binance isolation account is missing.

## Verification
- Targeted release/execution/regression suite: 82 passed after the final second-pass hardening.
- Python compilation: passed after the final second-pass hardening.
- Full pytest: still requires the unavailable `aiosqlite==0.22.1` package in this sandbox.
- Real PostgreSQL, Redis multi-worker, Cloud Run, exchange sandbox, Secret Manager, immutable logging and dependency CVE scans still require staging/CI verification.

## Production position
This release is a materially stronger fail-closed build, but it is not a claim of perfection. Real infrastructure drills remain mandatory before live customer funds are enabled.

## Final second-pass findings corrected

- Redis adaptive/executor lease refresh before submission.
- FX/commodity customer automation forced to paper/demo-only.
- Deriv executor live approval blocked; UI no longer presents it as a live path.
- Customer-isolated Binance reconciliation no longer depends on the platform default exchange or platform exchange credentials.
- Reconciled orders now move their durable `OrderCommand` to `RECONCILED`.
- Repeated customer order-not-found states now create durable reconciliation incidents.
- Alert records are `CONFIGURED`, not falsely marked `ACTIVE`, because no automatic alert evaluator is implemented.
- DCA/Grid START paths are fail-closed until an execution controller exists.

## Full-suite fact-check

`pytest -q` cannot complete in this sandbox because the runtime is missing `aiosqlite`; collection stops at `tests/test_billing.py`. This is an environment dependency limitation, not a claimed application test pass.
