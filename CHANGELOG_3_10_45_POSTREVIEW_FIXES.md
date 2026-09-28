# 3.10.45 post-review fixes

- db.py: Incident index referenced nonexistent `created_at`; now `opened_at` (matches migration 0033). App failed to import.
- customer_funds.settle_trading_fee: journal now debits the customer liability bucket(s) actually reduced (AVAILABLE and/or TRADING_RESERVED, split correctly) and credits EXPENSE:TRADING_FEES.
- customer_funds.settle_realized_pnl: idempotency check now runs before the affordability check so retries are no-ops.
- main.py: 8 `_safe_http_error` calls had swapped arguments (caused 500 TypeError); corrected.
- requirements-dev.txt: added pytest-asyncio.
- tests: replaced brittle source-text assertion for fee reserve consumption.
- Open: pip-audit flags ecdsa 0.19.2 (PYSEC-2026-1325, via bip-utils); PostgreSQL/Redis/sandbox gates still required.
- Verified: 368 passed, 1 skipped (PostgreSQL drill needs a live DB).

## Second pass (verified with pyflakes + runtime smoke)
- execution.py: added missing `or_`, `make_signal_id`, `client_order_id` imports and a best-effort `audit()` helper (new `audit_chain.record_audit`); `amount` -> `quantity` in live order command. Previously NameError on every order/reconcile/stop.
- main.py: initialised `_customer_jwks_cache` / `_jwks_refresh_lock` (all customer JWT checks failed); mounted `/static` and created `templates` (/, /admin returned 500); TemplateResponse uses the current Starlette signature.
- main.py: `customer_bot_status` was missing `for r in rows`; `customer_start_bot` now fetches derivatives context and fails closed on unavailable live context.
- main.py: route `release_withdrawal` shadowed the ledger function; ledger import aliased `ledger_release_withdrawal` (reject/fail/reconcile paths raised TypeError, stranding reserves).
- Withdrawals: reject only from PENDING/PARTIALLY_APPROVED/APPROVED; reconcile row-locked and only from SUBMITTING/SUBMITTED/UNKNOWN.
- New tests/test_static_name_integrity.py (undefined names, shadowed redefinitions, pages render). requirements-dev: pyflakes.
- NOT changed: FinancialNumeric returns Decimal while trading code multiplies by floats (TypeError confirmed) - needs a decision.

## Third pass
- db.FinancialNumeric now materializes float (was Decimal), matching its docstring and the float-native trading code. Fixes `Decimal * float` TypeError in paper fills, deposit scanner, funding webhook, withdrawal creation. Custodial ledger unaffected (own Numeric(38,6) columns).
- execution.py: entry-cooldown comparison tolerates naive datetimes (SQLite).
- New tests/test_paper_order_e2e.py: real paper buy+sell through execute_signal.
- Observation (not changed): a sell that reduces an existing long still required a protective stop in the discipline gate; verify intended behaviour.
