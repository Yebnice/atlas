# Atlas 3.10.18 — TRON Deposit/Reconciliation Engine

## Added
- Durable per-wallet TRON deposit scan cursor.
- Overlapping confirmed-history scans to tolerate polling gaps/restarts.
- TronGrid pagination via fingerprint.
- Exact TRC-20 USDT contract validation.
- Six-decimal USDT validation for the configured USDT contract.
- Optional transaction receipt verification through `walletsolidity/gettransactioninfobyid`.
- Idempotent funding transaction + double-entry ledger crediting.
- Customer trading-account balance synchronization after confirmed deposits.

## Safety
- Cursor advances only after the scan loop completes successfully.
- Failed/unknown transaction receipts are not credited.
- Customer balances are never supplied by the Android client.
- Existing live/funding flags were not changed.

## Verification
- Python compilation: PASS.
- Focused cross-system regression suite: 80 passed.
- Full pytest: collection blocked by missing `aiosqlite` in the execution environment; 1 skipped.
