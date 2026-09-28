# Atlas 3.10.13 — OANDA Failure-Mode Hardening

- Added a single read-only `resolve_unknown_order()` path for ambiguous OANDA order outcomes.
- Resolution uses direct `@clientOrderID` lookup first, then incremental transaction history when a durable cursor is available.
- No retry/resubmission is performed during unknown-order resolution.
- Reconciliation now passes the pre-update transaction cursor into unknown-order resolution.
- Added failure-injection tests for timeout/UNKNOWN behavior, duplicate-submission prevention, malformed streams, and missing quote timestamps.
- Bumped application version to 3.10.13.

Validation:
- Focused OANDA/FX/execution suite: 27 passed.
- `python -m py_compile app/*.py scripts/*.py`: passed.
- Full pytest collection remains blocked by missing environment dependency `aiosqlite`.
