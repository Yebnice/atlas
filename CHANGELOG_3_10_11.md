# Atlas 3.10.11 — OANDA v20 end-to-end reconciliation

- Added durable `OandaReconciliationState` cursor storage.
- Added OANDA `/v3/accounts/{accountID}/changes` account-snapshot polling.
- Demo enablement initializes the authoritative OANDA `lastTransactionID` cursor.
- Reconciliation advances the cursor and records sync/error state.
- Existing direct `@clientOrderID` lookup and transaction `sinceid` recovery remain enabled.
- Focused OANDA/FX/execution/arbitrage tests: 33 passed.
- Full pytest collection remains blocked by environment dependency `aiosqlite`.
- No live OANDA order authority is enabled by this change.
