# Atlas 3.10.22 — Ledger / Withdrawal / Confirmation Hardening

- Made the customer USDT ledger authoritative for withdrawal reservation, settlement, rejection, and provider failure/reconciliation.
- Prevented legacy wallet-balance synchronization from restoring funds already reserved for withdrawal.
- Added idempotent withdrawal reserve/release/settlement journal operations.
- Enforced the configured TRON minimum confirmation depth in addition to solidified receipt validation.
- Aligned Android version metadata with the backend release.
- Corrected a stale custody static test that referenced removed wording.

Validation boundary: Python compilation and targeted static/regression tests pass in the audit environment. The complete pytest suite remains blocked by unavailable `aiosqlite` installation in the isolated environment.
