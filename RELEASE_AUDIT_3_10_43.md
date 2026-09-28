# AtlasRisk 3.10.43 Release Audit

## Scope
This release applies the highest-priority live-money controls identified by the deep 3.10.42 architecture review. It deliberately fails closed on unsupported Deriv and Binance-arbitrage live paths instead of preserving unsafe direct execution.

## Live order lifecycle
1. Authenticate and resolve the customer's live entitlement.
2. Apply deterministic/risk/AI controls already present in AtlasRisk.
3. Create or recover a durable `OrderCommand`.
4. For cash-funded customer trades, persist the command together with the capital reservation.
5. Re-check live authority immediately before exchange submission.
6. Acquire the database live-execution lease and fencing token.
7. Verify the lease again before the broker call.
8. Submit exactly one idempotent client order through the supported broker adapter.
9. Apply the confirmed broker fill quantity to the position.
10. Verify the required protective stop.
11. If protection cannot be verified, halt new live trading and open a critical incident.
12. Persist exchange order identifiers and command state for reconciliation.

## Explicitly disabled paths
- Customer Deriv real-money execution
- Admin Deriv real-money execution
- Binance triangular-arbitrage live execution

These paths require a durable multi-leg transaction/reconciliation model before re-enablement.

## Residual external verification requirements
The container cannot prove Cloud Run multi-instance failover, PostgreSQL row-lock behavior against a real server, exchange-sandbox stop behavior, customer Secret Manager access, Cloud Logging retention, or dependency CVE results. Use `deploy/verify-live-money-runtime.sh` against a disposable PostgreSQL staging environment, then run the live-sandbox drills before enabling customer funds.


## Post-audit verification correction

The release identity was corrected after independent fact-checking found the application metadata still reported 3.10.42 while the release package was labelled 3.10.43. Runtime metadata and Android versioning now report 3.10.43. Obsolete 3.10.39 test assertions were updated without deleting the underlying feature tests.

### Verified after correction
- Release identity / execution regression subset: 43 passed.
- Migration graph: 36 revisions, 36 unique revisions, 0 missing parents, single head `0036_execution_control_plane`.
- Python compile check: passed.

### Not verified in this environment
- Full pytest suite: blocked at collection because `aiosqlite==0.22.1` is unavailable in the sandbox and package-network access is disabled.
- `bandit`: unavailable in the environment.
- `pip-audit`: unavailable in the environment.
- Real PostgreSQL concurrency/migration execution.
- Cloud Run multi-instance failover.
- Exchange sandbox stop/cancel behavior.
- Secret Manager / Cloud Logging runtime verification.
