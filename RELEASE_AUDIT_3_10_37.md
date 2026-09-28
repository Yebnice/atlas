# Atlas 3.10.37 Release Audit

## Scope
Built from the supplied `atlasrisk_3_10_36_fixed.zip` without pushing or modifying GitHub. Ghana-specific regulatory work is intentionally outside this release scope.

## Implemented

### P0 database/custody
- `tron_deposit_cursors.last_block_timestamp` is BIGINT.
- `tron_sweeps.amount_raw` is BIGINT.
- TRON cursor overlap converts configured seconds to milliseconds.
- Per-wallet TRON failures are isolated and audited.
- Per-wallet Redis locks prevent duplicate scans across worker instances.

### P1 security/admin
- Server-side RBAC roles: READ_ONLY, OPERATIONS, RISK_OFFICER, TREASURY, COMPLIANCE, ADMINISTRATOR.
- High-risk custody/withdrawal/live-control routes enforce roles server-side.
- Withdrawal destination fingerprints, cooling-off and explicit verification state.
- Audit log actor IDs and tamper-evident hash chain.
- Audit-chain verification endpoint.
- Database CHECK constraints for customer reserve and journal-line invariants.
- PostgreSQL foreign keys added as `NOT VALID` so legacy orphan cleanup can occur before validation.

### P2 runtime architecture
- `PROCESS_ROLE=api|worker|job`.
- API deployment disables embedded background loops and can scale horizontally.
- Cloud Run Worker Pool deployment script added.
- Cloud Run migration Job deployment script added.
- Exchange adapter boundary added around CCXT with capability discovery and order-state lookup.
- Production image no longer copies tests or the legacy trader artifact.

### Dependencies
- pydantic-settings 2.14.2
- pyarrow 23.0.1
- pytest 9.0.3

## Verification performed

- Python AST/compile verification: PASS.
- Bash deployment-script syntax: PASS.
- Focused existing regression tests: **18 passed** (`test_financial_precision_3_10_33.py`, `test_experiment_tracking_drift_3_10_36.py`).
- Synthetic SQLite execution of migration `0032_platform_hardening`: PASS for BIGINT conversion, audit columns, checks and RBAC/destination tables.
- Full pytest suite: **not completed** because the execution environment lacks `aiosqlite`, and outbound package installation is unavailable. This is an environment limitation, not recorded as a passing suite.
- Full PostgreSQL migration/concurrency test: **not completed** because `asyncpg` is also unavailable in the execution environment.
- `bandit`/`pip-audit`: not installed in the execution environment.

## Web-verified architecture basis

Google Cloud Run currently documents Services for HTTP workloads, Jobs for run-to-completion work such as migrations, and Worker Pools for continuous non-HTTP background work. CCXT documents a unified exchange API plus exchange-specific capability metadata. OWASP recommends server-side authorization and server-side transaction authorization.

## Release gate

This archive is a **review/staging hardening build**, not a claim of live-production certification. Before enabling live customer trading/custody, run the full dependency installation, PostgreSQL migration from empty schema, PostgreSQL concurrency/ledger invariants, worker failover, exchange idempotency/reconciliation and custody drills in a real staging environment.
